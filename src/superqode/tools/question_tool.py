"""
Question Tool - Ask User Clarifying Questions.

Allows agents to ask the user questions during task execution.
This enables interactive workflows where agents can:
- Clarify ambiguous requirements
- Get user preferences
- Confirm risky operations
- Present choices for implementation

Features:
- Multiple choice questions
- Free-form text input
- Confirmation dialogs
- Rating/ranking questions
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Awaitable

from .base import Tool, ToolResult, ToolContext


class QuestionType(Enum):
    """Type of question to ask."""

    TEXT = "text"  # Free-form text input
    CHOICE = "choice"  # Single selection from options
    MULTI_CHOICE = "multi_choice"  # Multiple selection from options
    CONFIRM = "confirm"  # Yes/no confirmation
    RATING = "rating"  # Rating on a scale


@dataclass
class Question:
    """A question to ask the user."""

    question: str
    question_type: QuestionType = QuestionType.TEXT
    options: List[str] = field(default_factory=list)
    default: Optional[str] = None
    allow_custom: bool = True
    min_rating: int = 1
    max_rating: int = 5


@dataclass
class Answer:
    """An answer from the user."""

    value: Any
    custom: bool = False


# Global question handler - set by the UI
_question_handler: Optional[Callable[[Question], Awaitable[Answer]]] = None


def set_question_handler(handler: Optional[Callable[[Question], Awaitable[Answer]]]) -> None:
    """Set the global question handler for UI integration."""
    global _question_handler
    _question_handler = handler


def get_question_handler() -> Optional[Callable[[Question], Awaitable[Answer]]]:
    """Get the current question handler."""
    return _question_handler


class QuestionTool(Tool):
    """
    Ask the user a question during execution.

    Allows agents to:
    - Get clarification on requirements
    - Present implementation choices
    - Confirm risky operations
    - Gather user preferences

    The question is presented through the UI and execution
    pauses until the user responds.
    """

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return """Ask the user a clarifying question.

Use this when you need:
- Clarification on ambiguous requirements
- User choice between implementation options
- Confirmation before risky operations
- User preferences for configuration

The question is shown to the user and execution pauses until they respond.
Use sparingly - prefer to make reasonable assumptions when possible."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the user"},
                "type": {
                    "type": "string",
                    "enum": ["text", "choice", "multi_choice", "confirm", "rating"],
                    "description": "Question type: text (free input), choice (single), multi_choice (multiple), confirm (yes/no), rating",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Options for choice/multi_choice questions",
                },
                "default": {
                    "type": "string",
                    "description": "Default value if user doesn't provide input",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": "Allow custom input in addition to options (default: true)",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context to show with the question",
                },
            },
            "required": ["question"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        question_text = args.get("question", "")
        question_type = args.get("type", "text")
        options = args.get("options", [])
        default = args.get("default")
        allow_custom = args.get("allow_custom", True)
        context = args.get("context", "")

        if not question_text:
            return ToolResult(success=False, output="", error="Question text is required")

        # Validate question type
        try:
            q_type = QuestionType(question_type)
        except ValueError:
            return ToolResult(
                success=False, output="", error=f"Invalid question type: {question_type}"
            )

        # Validate options for choice questions
        if q_type in (QuestionType.CHOICE, QuestionType.MULTI_CHOICE):
            if not options:
                return ToolResult(
                    success=False, output="", error="Options are required for choice questions"
                )

        # Create question object
        question = Question(
            question=question_text,
            question_type=q_type,
            options=options,
            default=default,
            allow_custom=allow_custom,
        )

        # Try to get answer through UI handler
        handler = get_question_handler()

        if handler:
            try:
                answer = await handler(question)
                return self._format_answer(answer, question, context)
            except asyncio.CancelledError:
                return ToolResult(success=False, output="", error="Question was cancelled")
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Error getting answer: {str(e)}")

        # Fallback: Use context output callback for simple text display
        if ctx.on_output:
            await ctx.emit_output(f"\n[Question] {question_text}\n")
            if options:
                await ctx.emit_output("Options:\n")
                for i, opt in enumerate(options, 1):
                    await ctx.emit_output(f"  {i}. {opt}\n")
            if default:
                await ctx.emit_output(f"Default: {default}\n")
            await ctx.emit_output("[Waiting for user response...]\n")

        # Without a UI handler, use default or return pending
        if default:
            return ToolResult(
                success=True,
                output=f"User response: {default}",
                metadata={"question": question_text, "answer": default, "used_default": True},
            )

        return ToolResult(
            success=False,
            output="",
            error="No question handler available and no default value provided. Run in interactive mode to ask questions.",
        )

    def _format_answer(self, answer: Answer, question: Question, context: str) -> ToolResult:
        """Format the answer as a tool result."""
        if question.question_type == QuestionType.CONFIRM:
            response = "Yes" if answer.value else "No"
        elif question.question_type == QuestionType.MULTI_CHOICE:
            if isinstance(answer.value, list):
                response = ", ".join(answer.value)
            else:
                response = str(answer.value)
        elif question.question_type == QuestionType.RATING:
            response = f"{answer.value}/{question.max_rating}"
        else:
            response = str(answer.value)

        output = f"User response: {response}"
        if answer.custom:
            output += " (custom input)"

        return ToolResult(
            success=True,
            output=output,
            metadata={
                "question": question.question,
                "type": question.question_type.value,
                "answer": answer.value,
                "custom": answer.custom,
            },
        )


class ConfirmTool(Tool):
    """
    Quick confirmation dialog.

    Simplified version of ask_user for yes/no confirmations.
    Use for confirming risky or irreversible operations.
    """

    @property
    def name(self) -> str:
        return "confirm"

    @property
    def description(self) -> str:
        return """Ask the user for a yes/no confirmation.

Use for:
- Confirming risky or destructive operations
- Verifying important decisions
- Getting go-ahead for changes

Returns 'confirmed' if user says yes, 'denied' if no."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to confirm"},
                "details": {
                    "type": "string",
                    "description": "Additional details about what will happen",
                },
                "default": {
                    "type": "boolean",
                    "description": "Default if user doesn't respond (default: false for safety)",
                },
            },
            "required": ["message"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        message = args.get("message", "")
        details = args.get("details", "")
        default = args.get("default", False)

        if not message:
            return ToolResult(success=False, output="", error="Confirmation message is required")

        # Create confirmation question
        question = Question(
            question=message,
            question_type=QuestionType.CONFIRM,
            options=["Yes", "No"],
            default="No" if not default else "Yes",
            allow_custom=False,
        )

        handler = get_question_handler()

        if handler:
            try:
                answer = await handler(question)
                confirmed = bool(answer.value)

                return ToolResult(
                    success=True,
                    output="confirmed" if confirmed else "denied",
                    metadata={"message": message, "confirmed": confirmed},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Confirmation failed: {str(e)}")

        # Fallback with context output
        if ctx.on_output:
            await ctx.emit_output(f"\n[Confirm] {message}\n")
            if details:
                await ctx.emit_output(f"Details: {details}\n")
            await ctx.emit_output("[Waiting for confirmation...]\n")

        # Use default for safety
        return ToolResult(
            success=True,
            output="denied" if not default else "confirmed",
            metadata={"message": message, "confirmed": default, "used_default": True},
        )
