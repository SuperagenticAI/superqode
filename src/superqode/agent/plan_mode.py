"""
Plan Mode for SuperQode Agent.

A planning-focused mode that analyzes tasks and creates execution plans
without executing any tools. The plan can then be reviewed and executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..agent.system_prompts import SystemPromptLevel, get_system_prompt


class PlanMode(str, Enum):
    """Plan mode types."""

    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"


@dataclass
class PlanConfig:
    """Configuration for plan mode."""

    enabled: bool = True
    max_plan_length: int = 2000
    require_approval: bool = True
    include_file_analysis: bool = True


@dataclass
class PlanStep:
    """A single step in a plan."""

    step_number: int
    description: str
    tool: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    reason: str = ""
    estimated_impact: str = ""


@dataclass
class Plan:
    """A complete execution plan."""

    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    estimated_files: List[str] = field(default_factory=list)
    potential_risks: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    created_by: str = ""


PLAN_MODE_SYSTEM_PROMPT = """You are in PLAN MODE. Your task is to analyze the user's request and create a detailed execution plan.

PLANNING RULES:
1. DO NOT execute any tools - only analyze and plan
2. Break down the task into clear, actionable steps
3. Identify which files need to be examined
4. Consider potential risks and edge cases
5. Define what success looks like

OUTPUT FORMAT:
Create a structured plan with:
- Goal: What we're trying to accomplish
- Steps: Numbered steps with tool suggestions
- Files: Which files need examination
- Risks: Potential issues to watch for
- Success: What done looks like

Remember: You're planning, not executing. The user will review your plan before execution."""

PLAN_MODE_USER_PROMPT = """You are in PLANNING mode. The agent will NOT execute any tools - it will only analyze and create a plan.

User request: {message}

Create a detailed execution plan. Use your knowledge of the codebase to identify:
- Which files need to be read/modified
- What tools would be needed (read_file, edit_file, bash, grep, etc.)
- Potential issues or risks
- How to verify success

DO NOT execute tools - just create the plan."""


class PlanModeAgent:
    """Agent that operates in plan mode - analyzes and plans without executing."""

    def __init__(
        self,
        config: Optional[PlanConfig] = None,
        working_directory: str = ".",
    ):
        self.config = config or PlanConfig()
        self.working_directory = working_directory
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build system prompt for plan mode."""
        base = get_system_prompt(
            SystemPromptLevel.EXPERT,
            self.working_directory,
        )
        return f"{base}\n\n{PLAN_MODE_SYSTEM_PROMPT}"

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def should_use_plan_mode(self, message: str) -> bool:
        """Determine if message should trigger plan mode."""
        plan_keywords = [
            "plan",
            "how would you",
            "what's the approach",
            "create a plan",
            "design",
            "architect",
            "strategy",
            "steps to",
            "break down",
            "analyze",
        ]
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in plan_keywords)

    def create_plan(self, message: str) -> str:
        """Get the plan mode user prompt for a message."""
        return PLAN_MODE_USER_PROMPT.format(message=message)

    def parse_plan_response(self, response: str) -> Optional[Plan]:
        """Parse a plan from the model's response."""
        plan = Plan(goal="")
        current_step: Optional[PlanStep] = None

        lines = response.split("\n")
        section = "intro"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_lower = line.lower()

            if "goal:" in line_lower or "objective:" in line_lower:
                section = "goal"
                plan.goal = line.split(":", 1)[1].strip() if ":" in line else ""

            elif "step" in line_lower and any(c.isdigit() for c in line[:5]):
                if current_step:
                    plan.steps.append(current_step)
                try:
                    step_num = int("".join(filter(str.isdigit, line[:3])))
                    current_step = PlanStep(
                        step_number=step_num,
                        description=line.split(".", 1)[1].strip() if "." in line else line,
                    )
                except ValueError:
                    pass

            elif "risk" in line_lower or "issue" in line_lower or "problem" in line_lower:
                section = "risks"
                if line_lower.startswith("-"):
                    plan.potential_risks.append(line.lstrip("- ").strip())

            elif "success" in line_lower or "done" in line_lower or "complete" in line_lower:
                section = "success"
                if line_lower.startswith("-"):
                    plan.success_criteria.append(line.lstrip("- ").strip())

            elif "file" in line_lower:
                section = "files"
                if line_lower.startswith("-"):
                    plan.estimated_files.append(line.lstrip("- ").strip())

            elif section == "goal" and not plan.goal:
                plan.goal = line

            elif current_step and not current_step.tool:
                if "tool:" in line_lower:
                    current_step.tool = line.split(":", 1)[1].strip()

        if current_step:
            plan.steps.append(current_step)

        return plan if plan.steps or plan.goal else None


def create_plan_mode_agent(
    working_directory: str = ".",
    config: Optional[PlanConfig] = None,
) -> PlanModeAgent:
    """Create a plan mode agent."""
    return PlanModeAgent(config=config, working_directory=working_directory)


def is_plan_request(message: str) -> bool:
    """Quick check if message is a planning request."""
    plan_indicators = [
        "plan",
        "how would",
        "create a plan",
        "design",
        "architect",
        "strategy",
        "break down the task",
        "steps to",
        "approach",
    ]
    return any(indicator in message.lower() for indicator in plan_indicators)
