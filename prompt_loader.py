"""Utility for loading prompts from external text files."""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class PromptLoader:
    """Loads prompts from external text files."""

    def __init__(self, prompts_dir: str = "prompts"):
        """Initialize the prompt loader.

        Args:
            prompts_dir: Directory containing prompt text files
        """
        # Get the project root directory (where prompts/ folder is located)
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # Go up from src/utils/ to project root
        self.prompts_dir = project_root / prompts_dir

        if not self.prompts_dir.exists():
            logger.warning("Prompts directory not found: %s", self.prompts_dir)

    def load_prompt(self, filename: str, **kwargs) -> str:
        """Load a prompt from a text file and format it with provided variables.

        Args:
            filename: Name of the prompt file (with or without .txt extension)
            **kwargs: Variables to format into the prompt template

        Returns:
            Formatted prompt string
        """
        if not filename.endswith('.txt'):
            filename += '.txt'

        prompt_path = self.prompts_dir / filename

        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompt_template = f.read()

        # Format the prompt with provided variables
        if kwargs:
            return prompt_template.format(**kwargs)
        return prompt_template

    def get_system_prompt(self, time_window_minutes: int = 120) -> str:
        """Get the meeting agent system prompt."""
        return self.load_prompt('meeting_agent_system_prompt.txt', time_window_minutes=time_window_minutes)

    def get_workflow_prompt(self, time_window_minutes: int, user_id: str, workflow_id: str) -> str:
        """Get the workflow execution prompt with formatted variables."""
        return self.load_prompt(
            'workflow_execution_prompt.txt',
            time_window_minutes=time_window_minutes,
            user_id=user_id,
            workflow_id=workflow_id
        )

    def get_elevation_ai_prompt(self, agent_task_id: str, platform_token: str) -> str:
        """Get the Elevation AI integration prompt with formatted variables."""
        return self.load_prompt(
            'elevation_ai_integration_prompt.txt',
            agent_task_id=agent_task_id,
            platform_token=platform_token
        )

    def get_enhanced_workflow_prompt(self, time_window_minutes: int, user_id: str, workflow_id: str,
                                   agent_task_id: str, platform_token: str) -> str:
        """Get the enhanced workflow execution prompt with Elevation AI integration."""
        return self.load_prompt(
            'enhanced_workflow_execution_prompt.txt',
            time_window_minutes=time_window_minutes,
            user_id=user_id,
            workflow_id=workflow_id,
            agent_task_id=agent_task_id,
            platform_token=platform_token
        )

    def get_ai_debrief_prompt(self, transcript_content: str) -> str:
        """Get the AI debrief prompt with transcript content."""
        return self.load_prompt(
            'ai_debrief_prompt.txt',
            transcript_content=transcript_content
        )


# Create a global instance for easy access
prompt_loader = PromptLoader()