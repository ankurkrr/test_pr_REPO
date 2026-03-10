from __future__ import annotations
import os
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError


# LangChain imports
from langchain.agents import AgentExecutor
from langchain.agents import create_structured_chat_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.memory import ConversationBufferWindowMemory

from src.services.integration.agent_integration_service import AgentIntegrationService
from src.services.integration.chain_visibility_service import ChainVisibilityService
from src.services.integration.data_flow_validator import DataFlowValidator
from src.services.integration.activity_logger import get_activity_logger
from src.services.integration.tool_data_flow_service import get_tool_data_flow_service
# from src.services.database_service import DatabaseService  # TODO: Replace with new service structure

# Core services
from src.services.integration.user_resolution_service import UserResolutionService, get_user_resolution_service
from src.utils.prompt_loader import PromptLoader

# Tools
from src.tools.langchain_calendar_tool import LangchainCalendarTool
from src.tools.langchain_dedup_tool import LangchainDedupTool
from src.tools.langchain_drive_tool import LangchainDriveTool
# Removed: langchain_elevation_ai_tool - replaced by unified_task_service
from src.tools.langchain_email_notification_tool import LangchainEmailNotificationTool
from src.tools.langchain_summarizer_tool import LangchainSummarizerTool

# Note: Model/key are read where needed to avoid import-time failures

logger = logging.getLogger(__name__)



# Note: GoogleAuthenticator is no longer used - replaced by GoogleAuthHandler
# GoogleSheetsService is now imported from src.services.google when needed


@dataclass
class WorkflowStep:
    """A single step in the agent's workflow."""

    step_number: int
    step_name: str
    description: str
    status: str = "pending"
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


@dataclass
class WorkflowState:
    """Stores the complete state for a running agent workflow."""

    session_id: str
    agent_id: str
    user_id: Optional[str] = None
    workflow_type: str = "unified_meeting_workflow"
    status: str = "running"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    steps: List[WorkflowStep] = field(default_factory=list)
    current_step: int = 0


class UnifiedMeetingAgent:
    """
    Production-ready unified agent:
    - Primary path: LangChain tools agent orchestrating 5-step workflow
    - Fallback path: Direct 3-step workflow (calendar -> drive -> summarizer)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, auth_tokens: Optional[Dict[str, Optional[str]]] = None):
        self.config = config or {}
        self.agent_id = self.config.get("agent_id", "meeting_agent")
        self.user_id = self.config.get("user_id")
        self.org_id = self.config.get("org_id")
        self.agent_task_id = self.config.get("agent_task_id")

        # Core services
        self.user_resolution = get_user_resolution_service()
        self.chain_visibility = ChainVisibilityService(enable_langsmith=True)
        self.data_validator = DataFlowValidator()
        self.agent_integration = AgentIntegrationService()
        self.activity_logger = get_activity_logger()
        self.data_flow_service = get_tool_data_flow_service()
        from src.services.database_service_new import get_database_service
        self.database_service = get_database_service()

        # State
        self.tools: List[BaseTool] = []
        self.agent_executor: Optional[AgentExecutor] = None
        self.auth = None

        # Init
        self.prompt_loader = PromptLoader()
        self._initialize_authentication(auth_tokens)
        self._initialize_tools()
        self._initialize_langchain_agent()

        # Ensure user_id is resolved
        if not self.user_id:
            self.user_id = self.user_resolution.ensure_user_id(self.user_id)

        logger.info("UnifiedMeetingAgent initialized: %s", self.agent_id)

    # --- Initialization helpers ---
    def _initialize_authentication(self, auth_tokens: Optional[Dict[str, Optional[str]]] = None) -> None:
        """Initializes Google authentication for service access."""
        try:
            from src.auth.google_auth_handler import get_google_auth_handler

            # Create auth handler - it will get tokens from database
            org_id = self.config.get("org_id", "default_org")
            self.auth = get_google_auth_handler(
                user_id=self.user_id,
                org_id=org_id,
                agent_task_id=self.agent_task_id 
            )

            # If tokens are provided from API payload, store them
            if auth_tokens and auth_tokens.get("access_token"):
                access_token = auth_tokens.get("access_token")
                refresh_token = auth_tokens.get("refresh_token")

                if self.auth.store_tokens(access_token, refresh_token):
                    logger.info("[OK] Google authentication ready with stored tokens")
                    return
                else:
                    logger.warning("[WARN] Token storage failed")

            # Check if we have valid tokens in database
            if self.auth.has_valid_tokens():
                logger.info("[OK] Google authentication ready with database tokens")
            else:
                logger.warning("[WARN] No valid Google tokens available")

        except Exception as e:
            logger.warning("Google authentication initialization failed: %s", e)
            self.auth = None

    def _initialize_tools(self) -> None:
        """
        Initialize tools needed for both agent and fallback paths.
        Agent tools: calendar, enhanced drive, summarizer, dedup, email
        Fallback-only: basic drive transcript matching tool
        """
        # Create instances with context
        # user_resolution.ensure_user_id(self.user_id) call is redundant if done at the end of __init__
        user_id = self.user_resolution.ensure_user_id(self.user_id)

        # Retrieve user resource IDs from database
        user_resources = self.database_service.get_user_resource_ids(user_id)
        drive_folder_id = user_resources.get("drive_folder_id")
        sheets_id = user_resources.get("sheets_id")

        logger.info(f"Retrieved user resources for {user_id}: drive_folder_id={drive_folder_id}, sheets_id={sheets_id}")

        self.calendar_tool = LangchainCalendarTool(
            auth=self.auth,
            agent_id=self.agent_id,
            user_id=user_id,
            workflow_id=f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            user_agent_task_id=self.agent_task_id,
        )
        
        # Use enhanced drive tool for better performance
        self.drive_tool = LangchainDriveTool(
            auth=self.auth,
            agent_id=self.agent_id,
            user_id=user_id,
            workflow_id=f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            user_agent_task_id=self.agent_task_id,
        )
        
        # Use enhanced summarizer tool with drive tool integration
        self.summarizer_tool = LangchainSummarizerTool(
            auth=self.auth,
            user_id=user_id,
            org_id=self.config.get("org_id"),
            agent_task_id=self.agent_task_id,
            drive_folder_id=drive_folder_id,
            drive_tool=self.drive_tool
        )
        # Initialize Dedup tool with sheets_id for Google Sheets interactions
        self.dedup_tool = LangchainDedupTool(auth=self.auth, sheets_id=sheets_id)
        self.email_tool = LangchainEmailNotificationTool(
            user_id=self.user_id,
            org_id=self.org_id,
            agent_task_id=self.agent_task_id,
            auth_handler=self.auth
        )

        # Tools exposed to the LLM agent
        self.tools = [
            self.calendar_tool,  # name: "calendar_tool"
            self.drive_tool,  # name: "drive_tool"
            self.summarizer_tool,  # name: "summarizer_tool"
            self.dedup_tool,  # name: "dedup_tool"
            self.email_tool,  # name: "email_notification_tool"
        ]

        logger.info(
            "Initialized %d tools for agent",
            len(self.tools),
        )

    def _initialize_langchain_agent(self) -> None:
        """Initialize the LangChain agent with LLM and tools."""
        # Use Gemini LLM if available
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

        if GEMINI_API_KEY:
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.1,
                google_api_key=GEMINI_API_KEY,
            )
            logger.info("Using Gemini LLM for LangChain agent")
        else:
            logger.error("GEMINI_API_KEY is missing from environment; cannot initialize Gemini LLM")
            raise ValueError("GEMINI_API_KEY is not set. Please configure it to use the Gemini LLM.")

        # --- Code that was incorrectly outside the class method ---
        # 1. Define the prompt template with required variables for structured chat agent
        # Resolve time window: prefer config, then environment, fallback to 30 minutes
        try:
            cfg_window = self.config.get("time_window_mins") if isinstance(self.config, dict) else None
        except Exception:
            cfg_window = None
        env_window = os.getenv("TIME_WINDOW_MINS")
        try:
            # Use CALENDAR_LOOKBACK_MINUTES from config if available, otherwise fallback to 30
            from ..configuration.config import CALENDAR_LOOKBACK_MINUTES
            resolved_window = int(cfg_window) if cfg_window is not None else int(env_window) if env_window else CALENDAR_LOOKBACK_MINUTES
        except Exception:
            resolved_window = 30  # Default to 30 minutes lookback

        system_prompt = self._create_system_prompt(time_window_mins=resolved_window)

        # Create a simple prompt template for tool calling agent
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""{system_prompt}

You are a meeting intelligence agent with access to various tools for calendar management, file operations, summarization, and communication.

Use the available tools to help answer the user's question. When you use a tool, provide a clear explanation of what you're doing and why."""),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad", optional=True),
        ])

        # 2. Create the Agent using create_tool_calling_agent
        from langchain.agents import create_tool_calling_agent
        agent = create_tool_calling_agent(llm, self.tools, prompt)

        # 3. Attach a small conversation memory window for minimal context retention
        try:
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)
        except Exception:
            memory = None

        # 4. Create the Executor
        self.agent_executor = AgentExecutor(
            agent=agent,  # Use the newly created agent
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=20,  # Increased to prevent early stopping
            early_stopping_method="force",
            memory=memory if memory else None,
        )
        # --- End of code moved back into method ---

        logger.info("LangChain agent initialized successfully")

    # --- Prompts ---
    def _create_system_prompt(self, time_window_mins: int = 120) -> str:
        """Loads and returns the agent's system prompt."""
        return self.prompt_loader.get_system_prompt(time_window_minutes=time_window_mins)

    def _create_workflow_prompt(self, time_window_mins: int = 120,
                               agent_task_id: Optional[str] = None,
                               platform_token: Optional[str] = None) -> str:
        """Creates the workflow execution prompt with Elevation AI integration."""
        workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if agent_task_id and platform_token:
            # Use enhanced workflow with Elevation AI integration
            return self.prompt_loader.get_enhanced_workflow_prompt(
                time_window_minutes=time_window_mins,
                user_id=self.user_id,
                workflow_id=workflow_id,
                agent_task_id=agent_task_id,
                platform_token=platform_token
            )
        else:
            # Use standard workflow without Elevation AI integration
            return self.prompt_loader.get_workflow_prompt(
                time_window_minutes=time_window_mins,
                user_id=self.user_id,
                workflow_id=workflow_id
            )

    def _create_elevation_ai_prompt(self, agent_task_id: str, platform_token: str) -> str:
        """Creates the Elevation AI integration prompt."""
        return self.prompt_loader.get_elevation_ai_prompt(agent_task_id, platform_token)

    # --- Introspection helpers used by API routes ---
    def get_agent_health(self) -> Dict[str, Any]:
        """Provides a simple health check status for the agent."""
        return {
            "status": "healthy",
            "agent_id": self.agent_id,
            "tools_initialized": len(self.tools) if self.tools else 0,
            "llm_configured": self.agent_executor is not None,
        }

    def get_workflow_tools_status(self) -> List[str]:
        """Lists the names of the tools available to the agent."""
        try:
            # Catching specific exceptions (e.g., AttributeError) is better, but
            # keeping general 'Exception' catch here for robustness if tool objects
            # are malformed. W0718 fix applied to keep the general structure.
            return [
                getattr(t, "name", t.__class__.__name__) for t in (self.tools or [])
            ]
        except Exception:
            logger.error("Error retrieving tool statuses.", exc_info=True)
            return []

    def execute_enhanced_workflow(self, agent_task_id: Optional[str] = None,
                                 platform_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute the enhanced 6-step workflow with Elevation AI platform integration.

        Args:
            agent_task_id: Optional agent task ID for platform integration
            platform_token: Optional platform token for Elevation AI integration

        Returns:
            Dict with enhanced workflow execution results including platform integration
        """
        logger.info(f"Starting enhanced workflow execution with Elevation AI integration for user: {self.user_id}")

        # Store Elevation AI parameters in config
        if agent_task_id:
            self.config["agent_task_id"] = agent_task_id
        if platform_token:
            self.config["platform_token"] = platform_token

        # Create enhanced workflow data structure with Elevation AI integration
        workflow_data = [
            {
                "id": "enhanced_meeting_intelligence_workflow",
                "text": "Execute enhanced meeting intelligence workflow with Elevation AI integration",
                "tool_to_use": [
                    {
                        "id": "calendar_tool",
                        "title": "Calendar Tool",
                        "fields_json": [{"field": "time_window", "value": "120"}]
                    },
                    {
                        "id": "enhanced_drive_tool",
                        "title": "Drive Tool",
                        "fields_json": [{"field": "search_query", "value": "meeting transcript"}]
                    },
                    {
                        "id": "summarizer_tool",
                        "title": "Summarizer Tool",
                        "fields_json": [{"field": "content", "value": "meeting_data"}]
                    },
                    {
                        "id": "dedup_tool",
                        "title": "Dedup Tool",
                        "fields_json": [{"field": "summary_data", "value": "JSON_FROM_SUMMARIZER"}]
                    },
                    {
                        "id": "email_notification_tool",
                        "title": "Email Tool",
                        "fields_json": [{"field": "summary_data", "value": "JSON_FROM_SUMMARIZER"}]
                    },
                ]
            }
        ]

        # Execute the enhanced workflow
        result = self._execute_workflow_with_prompts(workflow_data, agent_task_id, platform_token)

        # Add Elevation AI integration metrics
        if result.get("status") == "completed":
            result["elevation_ai_integration"] = {
                "enabled": bool(agent_task_id and platform_token),
                "agent_task_id": agent_task_id,
                "platform_token_provided": bool(platform_token),
                "integration_status": "completed" if agent_task_id and platform_token else "skipped"
            }

        logger.info(f"Enhanced workflow execution completed with Elevation AI integration: {result.get('status')}")
        return result

    def _execute_workflow_with_prompts(self, workflow_data: List[Dict[str, Any]],
                                      agent_task_id: Optional[str] = None,
                                      platform_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute workflow using enhanced prompts with Elevation AI integration.

        Args:
            workflow_data: List of workflow data items
            agent_task_id: Optional agent task ID for platform integration
            platform_token: Optional platform token for Elevation AI integration

        Returns:
            Dict with workflow execution results
        """
        logger.info(f"Executing workflow with enhanced prompts for user: {self.user_id}")

        try:
            # Create enhanced workflow prompt
            # Resolve time window again when building the workflow prompt
            try:
                cfg_window = self.config.get("time_window_mins") if isinstance(self.config, dict) else None
            except Exception:
                cfg_window = None
            env_window = os.getenv("TIME_WINDOW_MINS")
            try:
                resolved_window = int(cfg_window) if cfg_window is not None else int(env_window) if env_window else 30
            except Exception:
                resolved_window = 30

            workflow_prompt = self._create_workflow_prompt(
                time_window_mins=resolved_window,
                agent_task_id=agent_task_id,
                platform_token=platform_token
            )
            
            # Debug: Log the actual prompt being sent to the agent
            logger.info(f"Generated workflow prompt: {workflow_prompt[:500]}...")
            logger.info(f"Prompt contains time_window_minutes: {'time_window_minutes' in workflow_prompt}")
            logger.info(f"Prompt contains 120: {'120' in workflow_prompt}")

            # Execute using the agent executor with enhanced prompt and timeout
            if self.agent_executor:
                try:
                    # Cross-platform timeout using ThreadPoolExecutor
                    def _invoke_agent() -> Dict[str, Any]:
                        return self.agent_executor.invoke({"input": workflow_prompt, "chat_history": []})

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_invoke_agent)
                        try:
                            result = future.result(timeout=300)  # 5 minutes
                        except FuturesTimeoutError:
                            logger.error("Agent execution timed out after 5 minutes")
                            return {
                                "status": "failed",
                                "error": "Agent execution timed out",
                                "elevation_ai_enabled": bool(agent_task_id and platform_token)
                            }

                    return {
                        "status": "completed",
                        "session_id": f"enhanced_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        "workflow_type": "enhanced_with_elevation_ai",
                        "agent_result": result,
                        "elevation_ai_enabled": bool(agent_task_id and platform_token),
                        "execution_time": datetime.now().isoformat()
                    }
                except Exception as e:
                    logger.error(f"Agent execution failed: {e}")
                    return {
                        "status": "failed",
                        "error": f"Agent execution failed: {str(e)}",
                        "elevation_ai_enabled": bool(agent_task_id and platform_token)
                    }

        except Exception as e:
            logger.error(f"Enhanced workflow execution failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "elevation_ai_enabled": bool(agent_task_id and platform_token)
            }

    def execute_workflow(self, send_workflow_started_audit: bool = False) -> Dict[str, Any]:
        """
        Execute the meeting intelligence workflow for the current user.

        This method is called by the orchestrator to run the complete workflow.
        
        Args:
            send_workflow_started_audit: If True, sends "workflow_started" audit log.
                                        Set to False for scheduled runs (every 6 min) to avoid duplicates.
                                        Set to True for manual starts via API.

        Returns:
            Dict with workflow execution results
        """
        logger.info(f"Starting workflow execution for user: {self.user_id}")

        # Only send "workflow_started" audit for manual starts, not scheduled runs
        # Scheduled runs should only send status updates, not "workflow started" every 30 minutes
        if send_workflow_started_audit:
            self._send_audit_log("workflow_started", "Workflow execution started for user")

        try:
            # Use LangChain agent executor if available, otherwise fallback to direct execution
            if self.agent_executor:
                logger.info("🤖 Using LangChain AgentExecutor for workflow execution (will show green traces)")
                logger.info(f"AgentExecutor initialized: {self.agent_executor is not None}")
                logger.info(f"Available tools: {[tool.name for tool in self.tools]}")
                
                # Comprehensive query that instructs the agent to run the FULL workflow with ALL tools
                # Use configured lookback window for calendar events
                from ..configuration.config import CALENDAR_LOOKBACK_MINUTES
                lookback_minutes = CALENDAR_LOOKBACK_MINUTES
                query = (
                    f"Run the complete meeting intelligence workflow for user {self.user_id}. "
                    f"Execute the following steps in sequence using the available tools:\n"
                    f"1. Use the calendar_tool to find recent calendar events from the last {lookback_minutes} minutes\n"
                    f"2. Use the drive_tool to download meeting transcripts for any events found\n"
                    f"3. Use the summarizer_tool to generate AI summaries of the meeting content\n"
                    f"4. Use the dedup_tool to remove duplicate tasks and organize them\n"
                    f"5. Use the email_notification_tool to send notifications as needed\n"
                    f"\nExecute ALL steps using the LangChain agent with all available tools. "
                    f"Process each step completely before moving to the next."
                )
                
                logger.info(f"🤖 LangChain agent query: {query[:200]}...")
                result = self.agent_executor.invoke({
                    "input": query,
                    "chat_history": []
                })
                
                logger.info(f"LangChain agent execution completed. Result type: {type(result)}")
                
                # Convert agent result to expected format
                return {
                    "success": True,
                    "status": "completed",
                    "workflow_id": self.agent_task_id,
                    "agent_task_id": self.agent_task_id,
                    "agent_result": result,
                    "tasks_processed": self._extract_task_count_from_agent_result(result),
                    "meetings_found": self._extract_meeting_count_from_agent_result(result),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                logger.warning("[WARNING] AgentExecutor not available, using direct tool execution (no green traces)")
                logger.info(f"AgentExecutor status: {self.agent_executor}")
                logger.info(f"Tools available: {len(self.tools)}")
                result = self._execute_workflow_direct()
                return result

        except Exception as e:
            logger.error(f"Workflow execution failed for user {self.user_id}: {e}")
            return {
                "success": False,
                "status": "failed",
                "workflow_id": self.agent_task_id,
                "agent_task_id": self.agent_task_id,
                "error": str(e),
                "tasks_processed": 0,
                "meetings_found": 0
            }

    def _execute_workflow_direct(self) -> Dict[str, Any]:
        """
        Execute the workflow by directly calling tools in sequence.
        This bypasses the LangChain agent executor for more reliable data flow.
        """
        logger.info("Executing workflow using direct tool calls")
        
        # Initialize data flow service
        from ..configuration.config import CALENDAR_LOOKBACK_MINUTES
        workflow_data = {
            "user_id": self.user_id,
            "org_id": self.org_id,
            "agent_task_id": self.agent_task_id,
            "time_window_mins": CALENDAR_LOOKBACK_MINUTES
        }
        self.data_flow_service.set_workflow_data(workflow_data)
        
        results = {}
        
        try:
            # Step 1: Calendar Tool
            logger.info("Step 1: Executing Calendar Tool")
            calendar_data = self.data_flow_service.get_data_for_tool("calendar_tool")
            calendar_result = self.calendar_tool.run(calendar_data)
            self.data_flow_service.update_tool_result("calendar_tool", calendar_result)
            results["calendar_tool"] = calendar_result
            logger.info(f"Calendar tool completed: {type(calendar_result)}")

            # Step 2: Drive Tool
            logger.info("Step 2: Executing Drive Tool")
            drive_data = self.data_flow_service.get_data_for_tool("drive_tool")
            drive_result = self.drive_tool.run(json.dumps(drive_data))
            self.data_flow_service.update_tool_result("drive_tool", drive_result)
            results["drive_tool"] = drive_result
            logger.info(f"Drive tool completed: {type(drive_result)}")

            # Step 3: Summarizer Tool
            logger.info("Step 3: Executing Summarizer Tool")
            summarizer_data = self.data_flow_service.get_data_for_tool("summarizer_tool")
            summarizer_result = self.summarizer_tool.run(json.dumps(summarizer_data))
            self.data_flow_service.update_tool_result("summarizer_tool", summarizer_result)
            results["summarizer_tool"] = summarizer_result
            logger.info(f"Summarizer tool completed: {type(summarizer_result)}")

            # Step 4: Dedup Tool
            logger.info("Step 4: Executing Dedup Tool")
            dedup_data = self.data_flow_service.get_data_for_tool("dedup_tool")
            # Extract summary_data from the dedup_data dictionary
            summary_data_str = dedup_data.get("summary_data", "{}")
            dedup_result = self.dedup_tool.run(summary_data_str)
            
            # Parse dedup result to check for no tasks found
            try:
                if isinstance(dedup_result, str):
                    dedup_data = json.loads(dedup_result)
                else:
                    dedup_data = dedup_result
                
                if dedup_data.get("status") == "no_tasks_found":
                    logger.info("No tasks found in summary - this is normal for some meetings")
                    # Create a success result for no tasks found
                    dedup_result = json.dumps({
                        "status": "success",
                        "message": "No tasks found in summary",
                        "tasks_added": 0,
                        "tasks_processed": 0,
                        "timestamp": datetime.now().isoformat()
                    })
            except Exception as e:
                logger.warning(f"Failed to parse dedup result: {e}")
            
            self.data_flow_service.update_tool_result("dedup_tool", dedup_result)
            results["dedup_tool"] = dedup_result
            logger.info(f"Dedup tool completed: {type(dedup_result)}")

            # Step 5: Email Tool
            logger.info("Step 5: Executing Email Tool")
            email_data = self.data_flow_service.get_data_for_tool("email_notification_tool")
            
            # Extract parameters for email tool
            summary_data = email_data.get("summary_data", {})
            calendar_metadata = email_data.get("calendar_metadata", {})
            
            # Call email tool with proper parameters
            try:
                email_result = self.email_tool._run(
                    summary_data=json.dumps(summary_data),
                    calendar_metadata=calendar_metadata,
                    recipient_email=None,
                    subject=None
                )
                self.data_flow_service.update_tool_result("email_notification_tool", email_result)
                results["email_tool"] = email_result
                logger.info(f"Email tool completed: {type(email_result)}")
                # Emit friendly audit for email sent when successful
                try:
                    from ..services.integration.platform_api_client import PlatformAPIClient
                    import asyncio as _asyncio
                    _client = PlatformAPIClient()
                    # email_result may be JSON string; best-effort parse
                    import json as _json
                    _payload = None
                    if isinstance(email_result, str):
                        try:
                            _payload = _json.loads(email_result)
                        except Exception:
                            _payload = None
                    if _payload and _payload.get("status") == "success":
                        _client.send_simple_log_sync(
                            agent_task_id=getattr(self, 'agent_task_id', None),
                            log_text="Meeting summary email sent to participants.",
                            activity_type="task",
                            log_for_status="success",
                            action="Send",
                            action_issue_event="An email with the meeting summary and action items has been sent to all relevant participants, ensuring everyone stays informed and aligned.",
                            action_required="None",
                            outcome="Meeting summary and extracted tasks distributed via email.",
                            step_str="An email containing the meeting summary and extracted tasks has been sent successfully to the designated recipients. All meeting insights and action items are now available.",
                            tool_str="SendGrid",
                            log_data={"user_id": self.user_id, "org_id": getattr(self, 'org_id', None)}
                        )
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Email tool failed: {e}")
                # Create a fallback result for email tool
                email_result = json.dumps({
                    "status": "error",
                    "message": f"Email tool failed: {str(e)}",
                    "emails_sent": 0,
                    "timestamp": datetime.now().isoformat()
                })
                results["email_tool"] = email_result

            # Get workflow summary
            workflow_summary = self.data_flow_service.get_workflow_summary()
            
            return {
                "success": True,
                "status": "completed",
                "workflow_id": self.agent_task_id,
                "agent_task_id": self.agent_task_id,
                "workflow_summary": workflow_summary,
                "tool_results": results,
                "tasks_processed": self._extract_task_count(results),
                "meetings_found": self._extract_meeting_count(results),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Direct workflow execution failed: {e}")
            return {
                "success": False,
                "status": "failed",
                "workflow_id": self.agent_task_id,
                "agent_task_id": self.agent_task_id,
                "error": str(e),
                "tool_results": results,
                "workflow_summary": self.data_flow_service.get_workflow_summary(),
                "timestamp": datetime.now().isoformat()
            }

    def _extract_task_count(self, results: Dict[str, Any]) -> int:
        """Extract the number of tasks processed from tool results."""
        try:
            dedup_result = results.get("dedup_tool", {})
            if isinstance(dedup_result, str):
                dedup_data = json.loads(dedup_result)
            else:
                dedup_data = dedup_result
            
            return dedup_data.get("tasks_added", 0)
        except Exception:
            return 0

    def _extract_meeting_count(self, results: Dict[str, Any]) -> int:
        """Extract the number of meetings found from tool results."""
        try:
            calendar_result = results.get("calendar_tool", {})
            if isinstance(calendar_result, str):
                calendar_data = json.loads(calendar_result)
            else:
                calendar_data = calendar_result
            
            events = calendar_data.get("events", [])
            return len(events) if isinstance(events, list) else 0
        except Exception:
            return 0

    def _extract_task_count_from_agent_result(self, agent_result: Any) -> int:
        """Extract task count from LangChain agent result."""
        try:
            if isinstance(agent_result, dict):
                # Look for task count in various possible locations
                if "tasks_added" in agent_result:
                    return agent_result["tasks_added"]
                elif "tasks_processed" in agent_result:
                    return agent_result["tasks_processed"]
                elif "output" in agent_result and isinstance(agent_result["output"], str):
                    # Try to parse JSON from output
                    import json
                    try:
                        output_data = json.loads(agent_result["output"])
                        return output_data.get("tasks_added", 0)
                    except:
                        pass
            return 0
        except Exception:
            return 0

    def _extract_meeting_count_from_agent_result(self, agent_result: Any) -> int:
        """Extract meeting count from LangChain agent result."""
        try:
            if isinstance(agent_result, dict):
                # Look for meeting count in various possible locations
                if "meetings_found" in agent_result:
                    return agent_result["meetings_found"]
                elif "events_processed" in agent_result:
                    return agent_result["events_processed"]
                elif "output" in agent_result and isinstance(agent_result["output"], str):
                    # Try to parse JSON from output
                    import json
                    try:
                        output_data = json.loads(agent_result["output"])
                        return output_data.get("meetings_found", 0)
                    except:
                        pass
            return 0
        except Exception:
            return 0
    
    def _send_audit_log(self, action: str, message: str, details: Dict[str, Any] = None):
        """Helper method to send user-friendly audit logs to the platform."""
        try:
            from ..services.integration.platform_api_client import PlatformAPIClient
            import asyncio
            
            platform_client = PlatformAPIClient()
            agent_task_id = getattr(self, 'agent_task_id', None)
            
            # Map to friendly messages via simple sender; fallback to generic when action unknown
            if action == "workflow_started":
                from ..configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL
                platform_client.send_simple_log_sync(
                    agent_task_id=agent_task_id,
                    log_text="Meeting agent starts working for you successfully",
                    activity_type="workflow",
                    log_for_status="success",
                    action="Start",
                    action_issue_event="Meeting agent is now active and ready to work for you.",
                    action_required="None",
                    outcome="Meeting agent starts working for you successfully. Let's get the agent work for you and summarize your long transcripts in the best format of your understanding.",
                    step_str=f"Meeting agent starts working for you successfully. Let's get the agent work for you and summarize your long transcripts in the best format of your understanding. The agent will automatically check for new meetings every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes.",
                    tool_str="Meeting Agent",
                    log_data={"user_id": self.user_id, "org_id": getattr(self, 'org_id', None)}
                )
            else:
                # For non-workflow_started, use send_audit_log (still async)
                # Create task but handle event loop properly
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                loop.create_task(platform_client.send_audit_log({
                    "user_id": self.user_id,
                    "org_id": getattr(self, 'org_id', None),
                    "agent_task_id": agent_task_id,
                    "action": action,
                    "timestamp": datetime.now().isoformat(),
                    "details": details or {"message": message}
                }))
            logger.info(f"Sent audit log for action: {action}")
        except Exception as e:
            logger.warning(f"Failed to send audit log for {action}: {e}")

    def _run_scheduled_workflow(self, time_window_mins: int = 120) -> Dict[str, Any]:
        """
        Run scheduled workflow for calendar events in the specified time window.

        This method:
        1. Gets calendar events for the past time_window_mins
        2. For each event, builds a structured query for the AgentExecutor
        3. Invokes the agent with the structured query to process the event

        Args:
            time_window_mins: Time window in minutes to look back for events

        Returns:
            Dict with workflow execution results
        """
        logger.info(f"Starting scheduled workflow for user: {self.user_id}, time_window: {time_window_mins} minutes")

        # Import audit logger
        from src.utility.logging.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()

        # Log workflow start
        workflow_id = f"scheduled_{self.user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        audit_logger.log_scheduled_workflow_start(self.user_id, time_window_mins)

        start_time = datetime.now()

        try:
            # Step 1: Get calendar events for the specified time window
            logger.info(f"Fetching calendar events for the past {time_window_mins} minutes")
            # Get calendar events for both past and future time window - use configured lookback
            from ..configuration.config import CALENDAR_LOOKBACK_MINUTES
            calendar_result = self.calendar_tool.run({"minutes": CALENDAR_LOOKBACK_MINUTES})

            # Parse calendar result
            if isinstance(calendar_result, str):
                try:
                    calendar_data = json.loads(calendar_result)
                except json.JSONDecodeError:
                    logger.error("Failed to parse calendar result as JSON")
                    return {
                        "success": False,
                        "status": "error",
                        "workflow_id": workflow_id,
                        "agent_task_id": self.agent_task_id,
                        "error": "Failed to parse calendar data",
                        "events_processed": 0,
                        "events_found": 0
                    }
            else:
                calendar_data = calendar_result

            # Extract events from calendar data
            events = calendar_data.get("events", [])
            if not events:
                logger.info("No calendar events found in the specified time window")
                
                # Even without calendar events, search for recent meeting documents
                logger.info("Searching for recent meeting documents in Drive...")
                try:
                    # Search for recent documents that might be meeting transcripts
                    recent_docs_query = {
                        "operation": "search_recent_documents",
                        "query": "testing-3 OR meeting OR transcript OR notes OR summary",
                        "time_window_mins": time_window_mins,
                        "skip_already_processed": True
                    }
                    
                    # Use drive tool to search for recent documents
                    drive_result = self.drive_tool.run(json.dumps(recent_docs_query))
                    
                    if isinstance(drive_result, str):
                        try:
                            drive_data = json.loads(drive_result)
                        except json.JSONDecodeError:
                            drive_data = {"status": "error", "message": "Failed to parse drive result"}
                    else:
                        drive_data = drive_result
                    
                    # Check if any documents were found
                    transcripts_found = drive_data.get("transcripts_found", 0)
                    if transcripts_found > 0:
                        logger.info(f"Found {transcripts_found} recent documents without calendar events")
                        return {
                            "success": True,
                            "status": "completed",
                            "workflow_id": workflow_id,
                            "agent_task_id": self.agent_task_id,
                            "message": f"Found {transcripts_found} recent documents without calendar events",
                            "events_processed": transcripts_found,
                            "events_found": 0,
                            "time_window_mins": time_window_mins,
                            "drive_documents": drive_data.get("transcripts", [])
                        }
                    else:
                        logger.info("No recent documents found in Drive either")
                        return {
                            "success": True,
                            "status": "completed",
                            "workflow_id": workflow_id,
                            "agent_task_id": self.agent_task_id,
                            "message": "No events found in time window",
                            "events_processed": 0,
                            "events_found": 0,
                            "time_window_mins": time_window_mins
                        }
                        
                except Exception as e:
                    logger.error(f"Error searching for recent documents: {e}")
                    return {
                        "success": True,
                        "status": "completed",
                        "workflow_id": workflow_id,
                        "agent_task_id": self.agent_task_id,
                        "message": "No events found in time window",
                        "events_processed": 0,
                        "events_found": 0,
                        "time_window_mins": time_window_mins
                    }

            logger.info(f"Found {len(events)} calendar events to process")

            # Step 2: Process each event with structured LLM orchestration
            processed_events = []
            successful_events = 0
            failed_events = 0

            for i, event in enumerate(events):
                event_start_time = datetime.now()
                event_title = event.get('title', 'Untitled Event')
                event_id = event.get('id', f'event_{i}')

                try:
                    logger.info(f"Processing event {i+1}/{len(events)}: {event_title}")

                    # Build structured query for this specific event with Elevation AI integration
                    structured_query = self._build_structured_query_for_event(
                        event,
                        time_window_mins,
                        agent_task_id=self.agent_task_id,
                        platform_token=self.config.get("platform_token")
                    )

                    # Step 3: Invoke the agent with the structured query
                    if self.agent_executor:
                        logger.info(f"Invoking agent for event: {event_title}")
                        agent_result = self.agent_executor.invoke({"input": structured_query, "chat_history": []})

                        # Calculate processing time
                        processing_time_ms = int((datetime.now() - event_start_time).total_seconds() * 1000)

                        # Log event processed
                        audit_logger.log_event_processed(
                            workflow_id=workflow_id,
                            user_id=self.user_id,
                            event_title=event_title,
                            event_id=event_id,
                            status="success",
                            processing_time_ms=processing_time_ms
                        )

                        processed_events.append({
                            "event_index": i,
                            "event_title": event_title,
                            "event_id": event_id,
                            "agent_result": agent_result,
                            "status": "success",
                            "processing_time_ms": processing_time_ms
                        })
                        successful_events += 1
                        logger.info(f"Successfully processed event: {event_title}")
                    else:
                        logger.error("Agent executor not available")

                        # Log event processing failure
                        audit_logger.log_event_processed(
                            workflow_id=workflow_id,
                            user_id=self.user_id,
                            event_title=event_title,
                            event_id=event_id,
                            status="failed",
                            processing_time_ms=0
                        )

                        processed_events.append({
                            "event_index": i,
                            "event_title": event_title,
                            "event_id": event_id,
                            "status": "failed",
                            "error": "Agent executor not available"
                        })
                        failed_events += 1

                except Exception as e:
                    logger.error(f"Error processing event {i+1}: {e}")

                    # Log event processing error
                    audit_logger.log_error(
                        workflow_id=workflow_id,
                        user_id=self.user_id,
                        error_type="event_processing_error",
                        error_message=str(e),
                        error_context={"event_title": event_title, "event_id": event_id}
                    )

                    processed_events.append({
                        "event_index": i,
                        "event_title": event_title,
                        "event_id": event_id,
                        "status": "failed",
                        "error": str(e)
                    })
                    failed_events += 1

            # Calculate total execution time
            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Compile results
            result = {
                "success": successful_events > 0,
                "status": "completed" if successful_events > 0 else "failed",
                "workflow_id": workflow_id,
                "agent_task_id": self.agent_task_id,
                "events_found": len(events),
                "events_processed": successful_events,
                "events_failed": failed_events,
                "time_window_mins": time_window_mins,
                "processed_events": processed_events,
                "execution_time": datetime.now().isoformat(),
                "execution_time_ms": execution_time_ms
            }

            # Log workflow completion
            audit_logger.log_scheduled_workflow_stop(
                user_id=self.user_id,
                events_processed=successful_events,
                events_found=len(events),
                execution_time_ms=execution_time_ms
            )

            logger.info(f"Scheduled workflow completed: {successful_events} successful, {failed_events} failed")
            return result

        except Exception as e:
            logger.error(f"Scheduled workflow failed: {e}")

            # Log workflow error
            audit_logger.log_error(
                workflow_id=workflow_id,
                user_id=self.user_id,
                error_type="scheduled_workflow_error",
                error_message=str(e),
                error_context={"time_window_mins": time_window_mins}
            )

            return {
                "success": False,
                "status": "failed",
                "workflow_id": workflow_id,
                "agent_task_id": self.agent_task_id,
                "error": str(e),
                "events_processed": 0,
                "events_found": 0,
                "time_window_mins": time_window_mins
            }

    def _build_structured_query_for_event(self, event: Dict[str, Any], time_window_mins: int,
                                         agent_task_id: Optional[str] = None,
                                         platform_token: Optional[str] = None) -> str:
        """
        Build a structured query for the AgentExecutor to process a specific calendar event.

        The query instructs the agent to use the 5-step workflow:
        Calendar Tool → Drive Tool → Summarizer Tool → Deduplication Tool → Email Tool

        Args:
            event: Calendar event data
            time_window_mins: Time window for context
            agent_task_id: Optional agent task ID for platform integration
            platform_token: Optional platform token for Elevation AI integration

        Returns:
            Structured query string for the agent
        """
        event_title = event.get("title", "Untitled Event")
        event_id = event.get("id", "unknown")
        event_start = event.get("start", {}).get("dateTime", "unknown")
        event_end = event.get("end", {}).get("dateTime", "unknown")
        attendees = event.get("attendees", [])

        # Build attendee list
        attendee_emails = []
        if attendees:
            for attendee in attendees:
                if isinstance(attendee, dict) and "email" in attendee:
                    attendee_emails.append(attendee["email"])
                elif isinstance(attendee, str):
                    attendee_emails.append(attendee)

        attendee_list = ", ".join(attendee_emails) if attendee_emails else "No attendees listed"

        # Use enhanced workflow prompt if Elevation AI integration is available
        if agent_task_id and platform_token:
            workflow_prompt = self._create_workflow_prompt(
                time_window_mins=time_window_mins,
                agent_task_id=agent_task_id,
                platform_token=platform_token
            )
        else:
            workflow_prompt = self._create_workflow_prompt(time_window_mins=time_window_mins)

        # Create structured query with enhanced workflow
        structured_query = f"""
PROCESS MEETING EVENT: {event_title}

Event Details:
- Event ID: {event_id}
- Start Time: {event_start}
- End Time: {event_end}
- Attendees: {attendee_list}
- Time Window: Past {time_window_mins} minutes

{workflow_prompt}

SPECIFIC EVENT PROCESSING:
Execute the complete 6-step workflow for this specific meeting event:

STEP 1 - CALENDAR TOOL: Verify and retrieve event details
- Use calendar_tool to confirm event details and recent events
- Time window: Past {time_window_mins} minutes

STEP 2 - DRIVE TOOL: Search for meeting transcripts and documents
- Use enhanced_drive_tool to find files related to: "{event_title}"
- Look for transcripts, recordings, notes, or documents from the meeting
- Search for files created or modified around {event_start}
- Attendees to match: {attendee_list}

STEP 3 - SUMMARIZER TOOL: Process content and generate AI summary
- Use summarizer_tool to analyze any transcripts or documents found
- Generate executive summary, key decisions, and action items
- Extract tasks, decisions, and follow-up items from the meeting content
- Format: "summarize transcript content: [CONTENT] with meeting_title: {event_title} and attendees: [{attendee_list}]"

STEP 4 - DEDUPLICATION TOOL: Process and deduplicate extracted tasks
- Use dedup_tool to process the summary data from step 3
- Remove duplicate tasks and organize by assignee
- Store unique tasks in the user's Google Sheets
- Ensure tasks are properly categorized and prioritized

STEP 5 - EMAIL TOOL: Send meeting summary and tasks to participants
- Use email_notification_tool to send comprehensive meeting summary
- Include executive summary, key outcomes, and task assignments
- Recipients: {attendee_list}
- Include meeting context and metadata

EXECUTION ORDER: Execute these steps sequentially, using the output of each step as input for the next step.
Ensure all tools receive the proper data format and context for this specific meeting event.

Meeting Context: This is a scheduled workflow execution for event "{event_title}" that occurred in the past {time_window_mins} minutes.
"""

        logger.info(f"Built structured query for event: {event_title}")
        return structured_query


# --- Convenience factory helpers ---


def get_meeting_agent(config: Optional[Dict[str, Any]] = None, auth_tokens: Optional[Dict[str, Optional[str]]] = None) -> UnifiedMeetingAgent:
    """Return a new instance of UnifiedMeetingAgent for each user."""
    # Create a new instance for each user to avoid sharing state
    return UnifiedMeetingAgent(config=config, auth_tokens=auth_tokens)


def run_meeting_workflow(
    agent_task_id: str,
    workflow_data: List[Dict[str, Any]],
    auth_handler=None,
    user_id: Optional[str] = None,
    use_agent: bool = True,
    org_id: Optional[str] = None,
    #recipient_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Main runner now accepts auth_handler for Google authentication.
    auth_handler: GoogleAuthHandler instance with stored tokens
    Additional parameters:
    - org_id: Organization ID for multi-tenant support
    - recipient_scope: Recipient scope context for enhanced security
    """
    import asyncio
    
    # Convert auth_handler to auth_tokens format for backward compatibility
    auth_tokens = None
    if auth_handler and auth_handler.has_valid_tokens():
        tokens = auth_handler.get_latest_tokens()
        if tokens:
            auth_tokens = {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token
            }

    # Create agent with proper org_id context
    agent_config = {
        "user_id": user_id,
        "agent_task_id": agent_task_id,
        "org_id": org_id
    }
    agent = get_meeting_agent(agent_config, auth_tokens)

    workflow_state = WorkflowState(
        session_id=f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        agent_id="meeting_agent",
        user_id=user_id,
    )

    # Initialize ActivityLogger for platform logging
    activity_logger = get_activity_logger()
    
    # Helper function to log workflow steps to platform
    async def log_workflow_step_to_platform(step_name: str, description: str, status: str = "success", 
                                          tool_name: str = "Meeting Agent", outcome: str = "", 
                                          additional_data: Optional[Dict[str, Any]] = None):
        """Log workflow step to platform via ActivityLogger"""
        try:
            await activity_logger.log_workflow_step(
                agent_task_id=agent_task_id,
                step_name=step_name,
                tool_name=tool_name,
                status=status,
                description=description,
                outcome=outcome,
                action_type="Execute",
                additional_data=additional_data or {}
            )
        except Exception as e:
            logger.warning(f"Failed to log workflow step to platform: {e}")

    # Helper function to log workflow errors to platform
    async def log_workflow_error_to_platform(error_type: str, error_message: str, step_name: str = ""):
        """Log workflow error to platform via ActivityLogger"""
        try:
            await activity_logger.log_workflow_error(
                agent_task_id=agent_task_id,
                error_type=error_type,
                error_message=error_message,
                step_name=step_name,
                tool_name="Meeting Agent",
                user_id=user_id
            )
        except Exception as e:
            logger.warning(f"Failed to log workflow error to platform: {e}")

    try:
        # Log workflow start to platform
        try:
            # Check if we're already in an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an event loop, create a task instead
                loop.create_task(activity_logger.log_workflow_start(
                    agent_task_id=agent_task_id,
                    user_id=user_id,
                    workflow_items_count=len(workflow_data),
                    ip_address="127.0.0.1",  # Could be passed as parameter
                    user_agent="Meeting Intelligence Agent"
                ))
            except RuntimeError:
                # No event loop running, safe to use asyncio.run
                asyncio.run(activity_logger.log_workflow_start(
                    agent_task_id=agent_task_id,
                    user_id=user_id,
                    workflow_items_count=len(workflow_data),
                    ip_address="127.0.0.1",  # Could be passed as parameter
                    user_agent="Meeting Intelligence Agent"
                ))
        except Exception as e:
            logger.warning(f"Failed to log workflow start to platform: {e}")

        # Agent is already created above, use it
        workflow_state.steps.append(
            WorkflowStep(
                step_number=1,
                step_name="initialize_agent",
                description="Agent initialized with tools and services",
                status="completed",
                output_data={"tools": agent.get_workflow_tools_status()},
            )
        )

        # Log agent initialization step to platform
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(log_workflow_step_to_platform(
                step_name="initialize_agent",
                description="Agent initialized with tools and services",
                tool_name="Agent Initialization",
                outcome="Agent ready for workflow execution",
                additional_data={"tools_count": len(agent.tools), "user_id": user_id}
            ))
        except RuntimeError:
            asyncio.run(log_workflow_step_to_platform(
                step_name="initialize_agent",
                description="Agent initialized with tools and services",
                tool_name="Agent Initialization",
                outcome="Agent ready for workflow execution",
                additional_data={"tools_count": len(agent.tools), "user_id": user_id}
            ))

        # --- Parse workflow_data ---
        tool_context = {}
        for step in workflow_data:
            step_id = step.get("id")
            step_text = step.get("text")
            tools = step.get("tool_to_use", [])

            parsed = []
            for t in tools:
                fields = {
                    f.get("field"): f.get("value")
                    for f in t.get("fields_json", [])
                    if "field" in f
                }
                parsed.append(
                    {
                        "tool_title": t.get("title"),
                        "integration_type": t.get("integration_type"),
                        "integration_status": t.get("integration_status"),
                        "fields": fields,
                    }
                )

            tool_context[step_id] = {"text": step_text, "tools": parsed}

        workflow_state.steps.append(
            WorkflowStep(
                step_number=2,
                step_name="parse_workflow_data",
                description="Parsed API-provided workflow instructions",
                status="completed",
                output_data=tool_context,
            )
        )

        # Log workflow data parsing step to platform
        asyncio.run(log_workflow_step_to_platform(
            step_name="parse_workflow_data",
            description="Parsed API-provided workflow instructions",
            tool_name="Workflow Parser",
            outcome="Workflow data parsed and ready for execution",
            additional_data={"workflow_items_count": len(workflow_data), "tool_context_keys": list(tool_context.keys())}
        ))

        # --- Run agent path ---
        if use_agent and agent.agent_executor:
            query = (
                f"Run meeting workflow for task {agent_task_id}. "
                f"Context: {tool_context}"
            )
            logger.info("Executing agent with query: %s", query)

            # Log agent execution start to platform
            asyncio.run(log_workflow_step_to_platform(
                step_name="agent_execution_start",
                description="Starting LangChain agent execution",
                tool_name="LangChain Agent",
                outcome="Agent execution initiated",
                additional_data={"query_length": len(query), "use_agent": use_agent}
            ))

            result = agent.agent_executor.invoke({
                "input": query,
                "chat_history": []
            })
            
            workflow_state.steps.append(
                WorkflowStep(
                    step_number=3,
                    step_name="agent_execution",
                    description="LangChain agent executed using structured workflow_data",
                    status="completed",
                    input_data={"query": query},
                    output_data=result,
                )
            )

            # Log agent execution completion to platform
            asyncio.run(log_workflow_step_to_platform(
                step_name="agent_execution",
                description="LangChain agent executed using structured workflow_data",
                tool_name="LangChain Agent",
                outcome="Agent execution completed successfully",
                additional_data={"result_keys": list(result.keys()) if isinstance(result, dict) else "non_dict_result"}
            ))
            
            workflow_state.status = "completed"

        # --- Error handling for missing agent ---
        else:
            error_msg = "Agent executor not available" if not agent.agent_executor else "use_agent=False"
            logger.error(f"Cannot execute workflow: {error_msg}")
            
            # Log error to platform
            asyncio.run(log_workflow_step_to_platform(
                step_name="workflow_error",
                description="Workflow execution failed",
                tool_name="Workflow Engine",
                outcome="Workflow execution failed",
                additional_data={"error": error_msg}
            ))
            
            workflow_state.status = "failed"
            workflow_state.error = error_msg
            raise ValueError(f"Workflow execution failed: {error_msg}")

    except Exception as e:
        logger.error("Workflow execution failed: %s", e, exc_info=True)
        workflow_state.status = "failed"
        workflow_state.steps.append(
            WorkflowStep(
                step_number=len(workflow_state.steps) + 1,
                step_name="error",
                description="Failure in workflow execution",
                status="failed",
                error_message=str(e),
            )
        )

        # Log workflow error to platform
        asyncio.run(log_workflow_error_to_platform(
            error_type="WORKFLOW_EXECUTION_ERROR",
            error_message=str(e),
            step_name="workflow_execution"
        ))

    workflow_state.end_time = datetime.now()

    # Log workflow completion/stop to platform
    try:
        if workflow_state.status == "completed":
            asyncio.run(activity_logger.log_workflow_stop(
                agent_task_id=agent_task_id,
                user_id=user_id,
                reason="Workflow completed successfully",
                ip_address="127.0.0.1",
                user_agent="Meeting Intelligence Agent"
            ))
        else:
            asyncio.run(activity_logger.log_workflow_stop(
                agent_task_id=agent_task_id,
                user_id=user_id,
                reason=f"Workflow {workflow_state.status}",
                ip_address="127.0.0.1",
                user_agent="Meeting Intelligence Agent"
            ))
    except Exception as e:
        logger.warning(f"Failed to log workflow stop to platform: {e}")

    return {
        "session_id": workflow_state.session_id,
        "agent_task_id": agent_task_id,
        "status": workflow_state.status,
        "steps": [asdict(step) for step in workflow_state.steps],
        "start_time": workflow_state.start_time.isoformat(),
        "end_time": (
            workflow_state.end_time.isoformat() if workflow_state.end_time else None
        ),
    }


def stop_meeting_workflow(agent_task_id: str) -> Dict[str, Any]:
    """
    Stop the execution of a running meeting workflow.
    Marks workflow as stopped and cleans up state.
    """
    global _meeting_agent_instance

    if not _meeting_agent_instance:
        return {"status": "error", "message": "No active agent instance found"}

    try:
        # Mark state as stopped
        if hasattr(_meeting_agent_instance, "workflow_state"):
            _meeting_agent_instance.workflow_state.status = "stopped"
            _meeting_agent_instance.workflow_state.end_time = datetime.now()

        logger.info("Workflow stopped for agent_task_id=%s", agent_task_id)

        return {
            "status": "stopped",
            "agent_task_id": agent_task_id,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to stop workflow %s: %s", agent_task_id, e, exc_info=True)
        return {"status": "error", "message": f"Failed to stop workflow: {e}"}


def delete_meeting_agent(agent_id: str) -> Dict[str, Any]:
    """
    Soft delete a meeting agent.
    Marks the agent as deleted so it cannot be executed again.
    """
    global _meeting_agent_instance

    if not _meeting_agent_instance:
        return {"status": "error", "message": "No agent instance found to delete"}

    try:
        if hasattr(_meeting_agent_instance, "workflow_state"):
            _meeting_agent_instance.workflow_state.status = "deleted"
            _meeting_agent_instance.workflow_state.end_time = datetime.now()

        logger.info("Agent soft-deleted: %s", agent_id)

        return {
            "status": "deleted",
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to delete agent %s: %s", agent_id, e, exc_info=True)
        return {"status": "error", "message": f"Failed to delete agent: {e}"}