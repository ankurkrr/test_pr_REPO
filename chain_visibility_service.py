"""
Chain Execution Visibility Service
Provides structured logging and stepwise console output for LangChain applications
"""

import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
import uuid
from dataclasses import dataclass, field
from contextlib import contextmanager

# Optional import to avoid hard dependency cycles
try:
    from src.services.integration.agent_integration_service import AgentIntegrationService
except Exception:  # pragma: no cover
    AgentIntegrationService = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class StepExecution:
    """Represents a single step in the chain execution."""
    step_number: int
    step_name: str
    description: str
    status: str = "pending"  # pending, running, completed, failed
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChainExecution:
    """Represents the entire chain execution."""
    chain_id: str
    workflow_type: str
    user_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration: Optional[float] = None
    status: str = "running"  # running, completed, failed
    steps: List[StepExecution] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


class ChainVisibilityService:
    """
    Service for enhanced chain execution visibility with structured logging
    and real-time console output for LangChain applications.
    """

    def __init__(self, enable_langsmith: bool = False):
        self.current_chain: Optional[ChainExecution] = None
        self.current_step: Optional[StepExecution] = None
        self.enable_langsmith = enable_langsmith

        # Console formatting
        self.console_width = 80
        self.step_indent = "  "

        # Optional DB audit wiring
        self._agent_integration = None
        try:
            if AgentIntegrationService:
                self._agent_integration = AgentIntegrationService()
        except Exception:
            self._agent_integration = None

        # Correlation values for DB auditing
        self.user_agent_task_id: Optional[str] = None
        self.audit_context: Dict[str, Any] = {}

        # External platform logging client (async)
        try:
            from .platform_api_client import PlatformAPIClient
            self.platform_client = PlatformAPIClient()
        except Exception:
            self.platform_client = None

    async def log_agent_tool_execution(
        self,
        agent_task_id: str,
        tool_name: str,
        status: str,
        log_text: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Formats and sends a single tool execution log to the external platform.
        """
        log_for_status = "success" if status.lower() == "success" else "failed"
        payload = {
            "agent_task_id": agent_task_id,
            "logs": [
                {
                    "activity_type": "integration" if tool_name not in ["Summarizer Tool", "Dedup Tool"] else "task",
                    "log_for_status": log_for_status,
                    "log_text": log_text,
                    "action": "Complete" if log_for_status == "success" else "Error",
                    "action_issue_event": log_text,
                    "action_required": "None",
                    "outcome": status,
                    "step_str": f"Executed tool {tool_name} with status {status}.",
                    "tool_str": tool_name,
                    "log_data": details if details is not None else {},
                }
            ],
        }
        if not self.platform_client:
            return {"status": "error", "message": "Platform client unavailable"}
        request_id = f"log-{agent_task_id}-{uuid.uuid4().hex[:6]}"
        return await self.platform_client.send_audit_log_to_platform(payload, request_id=request_id)

        if enable_langsmith:
            logger.info("ChainVisibilityService initialized (LangSmith: True)")
        else:
            logger.info("ChainVisibilityService initialized (LangChain-only)")

    def start_chain(self, chain_id: str, workflow_type: str, user_id: str,
                   input_params: Optional[Dict[str, Any]] = None) -> ChainExecution:
        """Start a new chain execution."""
        self.current_chain = ChainExecution(
            chain_id=chain_id,
            workflow_type=workflow_type,
            user_id=user_id,
            start_time=datetime.now()
        )

        # DB audit: chain start
        if self._agent_integration and self.user_agent_task_id:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain",
                    log_for_status="success",
                    tool_name="langchain.chain.start",
                    log_text=f"Chain started: {workflow_type}",
                    log_data={"chain_id": chain_id, "input_params": input_params, **(self.audit_context or {})},
                    outcome="started",
                    scope="agent",
                    step_str="chain",
                    status=1,
                )
            except Exception:
                pass

        # Console output
        self._print_chain_header()

        # Structured logging
        logger.info(f"[START] CHAIN START: {workflow_type} (ID: {chain_id}, User: {user_id})")

        return self.current_chain

    def start_step(self, step_number: int, step_name: str, description: str,
                  input_data: Optional[Dict[str, Any]] = None) -> StepExecution:
        """Start a new step execution."""
        if not self.current_chain:
            raise ValueError("No active chain to add step to")

        self.current_step = StepExecution(
            step_number=step_number,
            step_name=step_name,
            description=description,
            status="running",
            start_time=datetime.now(),
            input_data=input_data
        )
        self.current_chain.steps.append(self.current_step)
        # DB audit: step start
        if self._agent_integration and self.user_agent_task_id:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain_step",
                    log_for_status="success",
                    tool_name="langchain.step.start",
                    log_text=f"Step started: {step_name}",
                    log_data={"step_number": step_number, "input_data": input_data, **(self.audit_context or {})},
                    outcome="started",
                    scope="agent",
                    step_str=step_name,
                    status=1,
                )
            except Exception:
                pass

            # Also log the chain start (only once at first step)
            try:
                if len(self.current_chain.steps) == 0:
                    self._agent_integration.log_agent_function(
                        user_agent_task_id=self.user_agent_task_id,
                        activity_type="chain",
                        log_for_status="success",
                        tool_name="langchain.chain.start",
                        log_text=f"Chain started: {self.current_chain.workflow_type}",
                        log_data={"chain_id": self.current_chain.chain_id, **(self.audit_context or {})},
                        outcome="started",
                        scope="agent",
                        step_str="chain",
                        status=1,
                    )
            except Exception:
                pass

        # Console output
        self._print_step_start()

        # Structured logging
        logger.info(f"[LIST] STEP {step_number}: {step_name} - {description}")

        return self.current_step

    def complete_step(self, output_data: Optional[Dict[str, Any]] = None,
                     metadata: Optional[Dict[str, Any]] = None):
        """Complete the current step."""
        if not self.current_step:
            raise ValueError("No active step to complete")

        self.current_step.end_time = datetime.now()
        self.current_step.duration_seconds = (
            self.current_step.end_time - self.current_step.start_time
        ).total_seconds()
        self.current_step.status = "completed"
        self.current_step.output_data = output_data
        if metadata:
            self.current_step.metadata.update(metadata)

        # Console output
        self._print_step_complete()

        # DB audit: step complete
        if self._agent_integration and self.user_agent_task_id:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain_step",
                    log_for_status="success",
                    tool_name="langchain.step.complete",
                    log_text=f"Step completed: {self.current_step.step_name}",
                    log_data={"duration": self.current_step.duration_seconds, "output": output_data, "metadata": metadata, **(self.audit_context or {})},
                    outcome="completed",
                    scope="agent",
                    step_str=self.current_step.step_name,
                    status=1,
                )
            except Exception:
                pass

        # Structured logging
        # DB audit: chain complete
        if self._agent_integration and self.user_agent_task_id and self.current_chain:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain",
                    log_for_status="success",
                    tool_name="langchain.chain.complete",
                    log_text="Chain completed",
                    log_data={"duration": self.current_chain.total_duration, "summary": self.current_chain.summary, **(self.audit_context or {})},
                    outcome="completed",
                    scope="agent",
                    step_str="chain",
                    status=1,
                )
            except Exception:
                pass

        logger.info(f"[OK] STEP {self.current_step.step_number} COMPLETED in {self.current_step.duration_seconds:.2f}s")

        self.current_step = None

    def fail_step(self, error_message: str, error_details: Optional[Dict[str, Any]] = None):
        """Mark the current step as failed."""
        if not self.current_step:
            raise ValueError("No active step to fail")

        self.current_step.end_time = datetime.now()
        self.current_step.duration_seconds = (
            self.current_step.end_time - self.current_step.start_time
        ).total_seconds()
        self.current_step.status = "failed"
        self.current_step.error_message = error_message
        if error_details:
            self.current_step.metadata.update(error_details)

        # Console output
        self._print_step_failed()

        # Structured logging
        logger.error(f"[ERROR] STEP {self.current_step.step_number} FAILED: {error_message}")

        # DB audit: step failed
        if self._agent_integration and self.user_agent_task_id:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain_step",
                    log_for_status="error",
                    tool_name="langchain.step.fail",
                    log_text=f"Step failed: {self.current_step.step_name}",
                    log_data={"duration": self.current_step.duration_seconds, "error": error_message, "error_details": error_details, **(self.audit_context or {})},
                    outcome="failed",
                    scope="agent",
                    step_str=self.current_step.step_name,
                    status=0,
                )
            except Exception:
                pass

        self.current_step = None

    def complete_chain(self, summary: Optional[Dict[str, Any]] = None):
        """Complete the current chain execution."""
        if not self.current_chain:
            raise ValueError("No active chain to complete")

        self.current_chain.end_time = datetime.now()
        self.current_chain.total_duration = (
            self.current_chain.end_time - self.current_chain.start_time
        ).total_seconds()
        self.current_chain.status = "completed"
        if summary:
            self.current_chain.summary = summary

        # Console output
        self._print_chain_complete()

        # Structured logging
        logger.info(f" CHAIN COMPLETED in {self.current_chain.total_duration:.2f}s")
        # DB audit: chain complete
        if self._agent_integration and self.user_agent_task_id and self.current_chain:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain",
                    log_for_status="success",
                    tool_name="langchain.chain.complete",
                    log_text="Chain completed",
                    log_data={"duration": self.current_chain.total_duration, "summary": self.current_chain.summary, **(self.audit_context or {})},
                    outcome="completed",
                    scope="agent",
                    step_str="chain",
                    status=1,
                )
            except Exception:
                pass

        completed_chain = self.current_chain
        self.current_chain = None

        # DB audit: chain complete
        if self._agent_integration and self.user_agent_task_id:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain",
                    log_for_status="success",
                    tool_name="langchain.chain.complete",
                    log_text="Chain completed",
                    log_data={"summary": self.current_chain.summary if self.current_chain else None, **(self.audit_context or {})},
                    outcome="completed",
                    scope="agent",
                    step_str="chain",
                    status=1,
                )
            except Exception:
                pass

        return completed_chain

    def fail_chain(self, error_message: str, error_details: Optional[Dict[str, Any]] = None):
        """Mark the current chain as failed."""
        if not self.current_chain:
            raise ValueError("No active chain to fail")


        # DB audit: chain failed
        if self._agent_integration and self.user_agent_task_id:
            try:
                self._agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="chain",
                    log_for_status="error",
                    tool_name="langchain.chain.fail",
                    log_text=error_message,
                    log_data={"error_details": error_details, **(self.audit_context or {})},
                    outcome="failed",
                    scope="agent",
                    step_str="chain",
                    status=0,
                )
            except Exception:
                pass

        self.current_chain.end_time = datetime.now()
        self.current_chain.total_duration = (
            self.current_chain.end_time - self.current_chain.start_time
        ).total_seconds()
        self.current_chain.status = "failed"

        # Console output
        self._print_chain_failed(error_message)

        # Structured logging
        logger.error(f" CHAIN FAILED: {error_message}")

        failed_chain = self.current_chain
        self.current_chain = None
        return failed_chain

    @contextmanager
    def step_context(self, step_number: int, step_name: str, description: str,
                    input_data: Optional[Dict[str, Any]] = None):
        """Context manager for step execution."""
        step = self.start_step(step_number, step_name, description, input_data)
        try:
            yield step
            self.complete_step()
        except Exception as e:
            self.fail_step(str(e), {"exception_type": type(e).__name__})
            raise

    def log_step_progress(self, message: str, data: Optional[Dict[str, Any]] = None):
        """Log progress within a step."""
        if self.current_step:
            print(f"{self.step_indent}    {message}")
            logger.info(f"STEP {self.current_step.step_number} PROGRESS: {message}")
            if data:
                logger.debug(f"STEP {self.current_step.step_number} DATA: {json.dumps(data, default=str)}")

    def _print_chain_header(self):
        """Print chain execution header."""
        print("\n" + "=" * self.console_width)
        print(f"[START] MEETING INTELLIGENCE CHAIN EXECUTION")
        print(f"   Workflow: {self.current_chain.workflow_type}")
        print(f"   Chain ID: {self.current_chain.chain_id}")
        print(f"   User ID: {self.current_chain.user_id}")
        print(f"   Started: {self.current_chain.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * self.console_width)

    def _print_step_start(self):
        """Print step start information."""
        print(f"\n{self.step_indent}[LIST] STEP {self.current_step.step_number}: {self.current_step.step_name}")
        print(f"{self.step_indent}   {self.current_step.description}")
        print(f"{self.step_indent}   [TIME]  Started: {self.current_step.start_time.strftime('%H:%M:%S')}")

    def _print_step_complete(self):
        """Print step completion information."""
        duration = self.current_step.duration_seconds
        print(f"{self.step_indent}   [OK] Completed in {duration:.2f}s")

        # Print key metrics if available
        if self.current_step.output_data:
            self._print_step_metrics()

    def _print_step_failed(self):
        """Print step failure information."""
        duration = self.current_step.duration_seconds
        print(f"{self.step_indent}   [ERROR] Failed after {duration:.2f}s")
        print(f"{self.step_indent}    Error: {self.current_step.error_message}")

    def _print_step_metrics(self):
        """Print step-specific metrics."""
        output = self.current_step.output_data
        if not output:
            return

        # Common metrics
        if "events_found" in output:
            print(f"{self.step_indent}   [DATA] Events found: {output['events_found']}")
        if "transcripts_found" in output:
            print(f"{self.step_indent}   [DATA] Transcripts found: {output['transcripts_found']}")
        if "summaries_generated" in output:
            print(f"{self.step_indent}   [DATA] Summaries generated: {output['summaries_generated']}")
        if "tasks_added" in output:
            print(f"{self.step_indent}   [DATA] Tasks added: {output['tasks_added']}")
        if "emails_sent" in output:
            print(f"{self.step_indent}   [DATA] Emails sent: {output['emails_sent']}")

    def _print_chain_complete(self):
        """Print chain completion summary."""
        print(f"\n{self.step_indent} CHAIN EXECUTION COMPLETED")
        print(f"{self.step_indent}   [TIME]  Total duration: {self.current_chain.total_duration:.2f}s")
        print(f"{self.step_indent}   [DATA] Steps completed: {len([s for s in self.current_chain.steps if s.status == 'completed'])}")
        print(f"{self.step_indent}   [ERROR] Steps failed: {len([s for s in self.current_chain.steps if s.status == 'failed'])}")

        # Print summary metrics
        if self.current_chain.summary:
            print(f"{self.step_indent}   [UP] Final Results:")
            for key, value in self.current_chain.summary.items():
                if isinstance(value, (int, float, str)):
                    print(f"{self.step_indent}      {key}: {value}")

        print("=" * self.console_width)

    def _print_chain_failed(self, error_message: str):
        """Print chain failure information."""
        print(f"\n{self.step_indent} CHAIN EXECUTION FAILED")
        print(f"{self.step_indent}   [TIME]  Duration: {self.current_chain.total_duration:.2f}s")
        print(f"{self.step_indent}    Error: {error_message}")
        print("=" * self.console_width)

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get a summary of the current or last chain execution."""
        if not self.current_chain:
            return {"error": "No chain execution available"}

        return {
            "chain_id": self.current_chain.chain_id,
            "workflow_type": self.current_chain.workflow_type,
            "user_id": self.current_chain.user_id,
            "status": self.current_chain.status,
            "start_time": self.current_chain.start_time.isoformat(),
            "end_time": self.current_chain.end_time.isoformat() if self.current_chain.end_time else None,
            "total_duration": self.current_chain.total_duration,
            "steps": [
                {
                    "step_number": step.step_number,
                    "step_name": step.step_name,
                    "status": step.status,
                    "duration": step.duration_seconds,
                    "error": step.error_message
                }
                for step in self.current_chain.steps
            ],
            "summary": self.current_chain.summary
        }


# Global instance for easy access
_chain_visibility_service = None

def get_chain_visibility_service() -> ChainVisibilityService:
    """Get the global ChainVisibilityService instance."""
    global _chain_visibility_service
    if _chain_visibility_service is None:
        _chain_visibility_service = ChainVisibilityService()
    return _chain_visibility_service