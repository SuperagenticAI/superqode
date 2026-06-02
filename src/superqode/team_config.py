"""Team configuration helpers shared by the Textual app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class TeamRole:
    """Represents a configured team role."""

    mode: str
    role: str
    description: str
    model: str
    provider: str
    coding_agent: str
    enabled: bool
    job_description: str = ""
    execution_mode: str = "acp"
    agent: str = ""

    @property
    def command(self) -> str:
        return f":{self.mode} {self.role}"

    @property
    def display_name(self) -> str:
        return f"{self.mode.upper()}.{self.role}"

    @property
    def exec_mode_display(self) -> str:
        if self.execution_mode == "acp":
            return f"ACP*{self.agent or self.coding_agent}"
        return f"BYOK*{self.provider}"


@dataclass
class TeamConfig:
    """Team configuration loaded from YAML."""

    team_name: str
    description: str
    roles: List[TeamRole]

    @property
    def enabled_roles(self) -> List[TeamRole]:
        return [r for r in self.roles if r.enabled]

    @property
    def enabled_count(self) -> int:
        return len(self.enabled_roles)

    def get_roles_by_mode(self, mode: str) -> List[TeamRole]:
        return [r for r in self.roles if r.mode == mode]

    def get_enabled_roles_by_mode(self, mode: str) -> List[TeamRole]:
        return [r for r in self.enabled_roles if r.mode == mode]


def load_team_config() -> TeamConfig:
    """Load team configuration from superqode.yaml."""
    try:
        from superqode.config import load_config

        config = load_config()

        team_name = "Development Team"
        description = "AI-powered software development team"

        if hasattr(config, "superqode") and config.superqode:
            team_name = getattr(config.superqode, "team_name", team_name)
            description = getattr(config.superqode, "description", description)

        roles = []

        if hasattr(config, "team") and config.team and hasattr(config.team, "modes"):
            for mode_name, mode_config in config.team.modes.items():
                if hasattr(mode_config, "roles") and mode_config.roles:
                    for role_name, role_config in mode_config.roles.items():
                        enabled = getattr(role_config, "enabled", True)

                        exec_mode = getattr(role_config, "mode", "")
                        agent_id = getattr(role_config, "agent", "")
                        coding_agent = getattr(role_config, "coding_agent", "opencode")

                        if not exec_mode:
                            if agent_id or (
                                coding_agent
                                and coding_agent not in ("superqode", "superqode", "byok")
                            ):
                                exec_mode = "acp"
                            else:
                                exec_mode = "byok"

                        model = getattr(role_config, "model", "")
                        provider = getattr(role_config, "provider", "")

                        agent_config = getattr(role_config, "agent_config", None)
                        if agent_config:
                            if not model:
                                model = getattr(agent_config, "model", "minimax-m2.5-free")
                            if not provider:
                                provider = getattr(agent_config, "provider", "")

                        roles.append(
                            TeamRole(
                                mode=mode_name,
                                role=role_name,
                                description=getattr(role_config, "description", ""),
                                model=model or "minimax-m2.5-free",
                                provider=provider or "opencode",
                                coding_agent=coding_agent,
                                enabled=enabled,
                                job_description=getattr(role_config, "job_description", ""),
                                execution_mode=exec_mode,
                                agent=agent_id or coding_agent,
                            )
                        )

        return TeamConfig(team_name=team_name, description=description, roles=roles)

    except Exception:
        return TeamConfig(
            team_name="Development Team",
            description="AI-powered software development team",
            roles=[
                TeamRole(
                    "dev",
                    "fullstack",
                    "Full-stack development",
                    "minimax-m2.5-free",
                    "opencode",
                    "opencode",
                    True,
                    "",
                    "acp",
                    "opencode",
                ),
                TeamRole(
                    "qe",
                    "fullstack",
                    "Full-stack QE",
                    "nemotron-3-super-free",
                    "opencode",
                    "opencode",
                    True,
                    "",
                    "acp",
                    "opencode",
                ),
                TeamRole(
                    "devops",
                    "fullstack",
                    "Full-stack DevOps",
                    "minimax-m2.5-free",
                    "opencode",
                    "opencode",
                    True,
                    "",
                    "acp",
                    "opencode",
                ),
            ],
        )


__all__ = ["TeamConfig", "TeamRole", "load_team_config"]
