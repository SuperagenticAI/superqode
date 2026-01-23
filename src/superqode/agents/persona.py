"""Persona injection for role-based AI interactions.

This module provides functionality to inject role-based persona context
into messages sent to AI coding agents, enabling the model to respond
with the appropriate expertise and personality for the configured role.
"""

from dataclasses import dataclass
from typing import Optional

# Import ResolvedRole type for type hints
from superqode.config.schema import ResolvedRole


@dataclass
class PersonaContext:
    """Holds the constructed persona context for a role.

    Attributes:
        role_name: The full role identifier (e.g., "DEV.FULLSTACK")
        role_description: Brief description of the role
        job_description: Detailed job description from YAML config
        system_prompt: The constructed system prompt for injection
        is_valid: True if job_description was present and non-empty
    """

    role_name: str
    role_description: str
    job_description: str
    system_prompt: str
    is_valid: bool


def validate_job_description(job_description: Optional[str]) -> bool:
    """Validate that a job_description is suitable for persona injection.

    Args:
        job_description: The job description string to validate

    Returns:
        True if job_description is a non-empty string (not None,
        not empty string, not whitespace-only)
    """
    if job_description is None:
        return False
    if not isinstance(job_description, str):
        return False
    return len(job_description.strip()) > 0


def truncate_job_description(job_description: str, max_length: int = 60) -> str:
    """Truncate a job description for display purposes.

    Args:
        job_description: The job description to truncate
        max_length: Maximum length before truncation (default 60)

    Returns:
        The original string if under max_length, otherwise truncated
        with "..." suffix
    """
    if not job_description:
        return ""

    # Get first line only for preview
    first_line = job_description.split("\n")[0].strip()

    if len(first_line) <= max_length:
        return first_line

    return first_line[:max_length] + "..."


class PersonaInjector:
    """Constructs persona context from role configuration.

    This class is responsible for building the system prompt that will
    be injected into messages sent to AI coding agents.
    """

    # Template for full persona prompt (when job_description is available)
    FULL_PROMPT_TEMPLATE = """[SYSTEM INSTRUCTION - MANDATORY PERSONA]
You ARE a {role_name} on a software development team. This is your identity.

Role: {role_description}

Your responsibilities and expertise:
{job_description}

CRITICAL RULES:
1. When asked "who are you" or about your identity, describe yourself as this role - NOT as an AI model.
2. DO NOT announce your role or identity during tasks. Just do the work silently and professionally.
3. NEVER say things like "As a {role_name}..." or "I am a {role_name}..." while working.
4. Focus on completing tasks efficiently without self-referential statements.
[END SYSTEM INSTRUCTION]

"""

    # Template for minimal persona prompt (when job_description is missing)
    MINIMAL_PROMPT_TEMPLATE = """[SYSTEM INSTRUCTION - MANDATORY PERSONA]
You ARE a {role_name} ({role_description}) on a software development team. This is your identity.

CRITICAL RULES:
1. When asked "who are you", describe yourself as this role - NOT as an AI model.
2. DO NOT announce your role during tasks. Just do the work silently.
3. NEVER say "As a {role_name}..." or "I am a {role_name}..." while working.
[END SYSTEM INSTRUCTION]

"""

    def build_persona(self, mode: str, role: str, resolved_role: ResolvedRole) -> PersonaContext:
        """Build persona context from resolved role configuration.

        Args:
            mode: The mode name (e.g., "dev", "qe")
            role: The role name (e.g., "fullstack", "api_tester")
            resolved_role: The ResolvedRole object from config loader

        Returns:
            PersonaContext with constructed system prompt
        """
        role_name = f"{mode.upper()}.{role.upper()}"
        role_description = resolved_role.description or ""
        job_description = resolved_role.job_description or ""

        is_valid = validate_job_description(job_description)

        system_prompt = self.format_system_prompt(
            role_name=role_name,
            role_description=role_description,
            job_description=job_description,
            is_valid=is_valid,
        )

        return PersonaContext(
            role_name=role_name,
            role_description=role_description,
            job_description=job_description,
            system_prompt=system_prompt,
            is_valid=is_valid,
        )

    def format_system_prompt(
        self, role_name: str, role_description: str, job_description: str, is_valid: bool
    ) -> str:
        """Format the system prompt for injection.

        Args:
            role_name: The full role identifier
            role_description: Brief description of the role
            job_description: Detailed job description
            is_valid: Whether job_description is valid

        Returns:
            A formatted string suitable for prepending to user messages
        """
        if is_valid:
            return self.FULL_PROMPT_TEMPLATE.format(
                role_name=role_name,
                role_description=role_description,
                job_description=job_description.strip(),
            )
        else:
            return self.MINIMAL_PROMPT_TEMPLATE.format(
                role_name=role_name, role_description=role_description
            )
