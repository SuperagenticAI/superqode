"""Declarative launch profiles for coding harnesses.

Profiles only use per-process arguments and environment variables. They never
rewrite a developer's harness configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
from typing import Mapping, Sequence


@dataclass(frozen=True)
class HarnessProfile:
    id: str
    label: str
    executables: tuple[str, ...]
    integration: str
    protocol: str
    default_provider: str
    support: str = "gateway"
    note: str = ""

    def executable(self) -> str | None:
        return next((path for name in self.executables if (path := shutil.which(name))), None)


@dataclass(frozen=True)
class LaunchPlan:
    profile: HarnessProfile
    command: tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    generated_files: Mapping[str, str] = field(default_factory=dict)
    note: str = ""


_PROFILES = (
    HarnessProfile(
        "codex",
        "OpenAI Codex CLI",
        ("codex",),
        "one-off authenticated model-provider override",
        "OpenAI Responses",
        "openai",
        support="gateway-limited",
        note=(
            "Codex 0.155 subscription requests use server-side tool injection and expose no "
            "tool catalogue to the gateway; a native/app-server hook is required for routing."
        ),
    ),
    HarnessProfile(
        "claude",
        "Claude Code",
        ("claude",),
        "ANTHROPIC_BASE_URL process environment",
        "Anthropic Messages",
        "anthropic",
    ),
    HarnessProfile(
        "opencode",
        "OpenCode",
        ("opencode",),
        "OPENCODE_CONFIG_CONTENT runtime overlay",
        "OpenAI or Anthropic",
        "openai",
    ),
    HarnessProfile(
        "grok",
        "Grok Build",
        ("grok",),
        "GROK_MODELS_BASE_URL process environment",
        "OpenAI Responses",
        "xai",
        note="Custom endpoints use API-key authentication; subscription login is not forwarded.",
    ),
    HarnessProfile(
        "pi",
        "Pi coding agent",
        ("pi",),
        "isolated PI_CODING_AGENT_DIR with a generated provider",
        "OpenAI or Anthropic",
        "anthropic",
        note="A model id is required; the temporary profile uses provider API-key authentication.",
    ),
    HarnessProfile(
        "antigravity",
        "Google Antigravity CLI",
        ("agy",),
        "no model endpoint hook exposed by the CLI",
        "private transport",
        "google",
        support="detect-only",
        note="Detected and tracked, but the current CLI cannot be routed without a maintained fork.",
    ),
    HarnessProfile(
        "superqode",
        "SuperQode",
        ("superqode",),
        "native System One router",
        "native provider gateway",
        "openai",
        support="native",
    ),
)
_PROFILE_MAP = {profile.id: profile for profile in _PROFILES}


def profiles() -> tuple[HarnessProfile, ...]:
    return _PROFILES


def get_profile(name: str) -> HarnessProfile:
    try:
        return _PROFILE_MAP[name.lower()]
    except KeyError as exc:
        choices = ", ".join(_PROFILE_MAP)
        raise ValueError(f"unknown harness {name!r}; choose one of: {choices}") from exc


def build_launch_plan(
    profile: HarnessProfile,
    *,
    gateway_url: str,
    provider: str,
    model: str = "",
    extra_args: Sequence[str] = (),
    temp_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LaunchPlan:
    """Build a non-persistent launch plan for one harness."""
    executable = profile.executable() or profile.executables[0]
    args = tuple(extra_args)
    env: dict[str, str] = {}
    base_v1 = gateway_url.rstrip("/") + "/v1"
    current_env = environ or os.environ

    if profile.id == "codex":
        return LaunchPlan(
            profile,
            (
                executable,
                "-c",
                'model_provider="superqode_jev"',
                "-c",
                'model_providers.superqode_jev.name="SuperQode Jev Tool Routing"',
                "-c",
                f'model_providers.superqode_jev.base_url="{base_v1}"',
                "-c",
                'model_providers.superqode_jev.wire_api="responses"',
                "-c",
                "model_providers.superqode_jev.requires_openai_auth=true",
                "-c",
                "model_providers.superqode_jev.supports_websockets=false",
                "-c",
                "features.enable_request_compression=false",
                *args,
            ),
        )
    if profile.id == "claude":
        env["ANTHROPIC_BASE_URL"] = gateway_url.rstrip("/")
        return LaunchPlan(profile, (executable, *args), env)
    if profile.id == "opencode":
        if provider == "google":
            if not model:
                raise ValueError("OpenCode with Google needs --model")
            overlay = {"provider": {"google": {"options": {"baseURL": base_v1 + "beta"}}}}
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(overlay, separators=(",", ":"))
            # The Google AI SDK refuses to construct a client without this
            # provider-specific variable.  It only reaches our loopback
            # gateway; the gateway replaces it with GEMINI_API_KEY upstream.
            env["GOOGLE_GENERATIVE_AI_API_KEY"] = "superqode-local-gateway"
            return LaunchPlan(
                profile,
                (executable, "--model", f"google/{model}", *args),
                env,
            )
        provider_id = {"xai": "xai", "anthropic": "anthropic"}.get(provider, "openai")
        overlay = {"provider": {provider_id: {"options": {"baseURL": base_v1}}}}
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(overlay, separators=(",", ":"))
        return LaunchPlan(profile, (executable, *args), env)
    if profile.id == "grok":
        env["GROK_MODELS_BASE_URL"] = base_v1
        return LaunchPlan(profile, (executable, *args), env, note=profile.note)
    if profile.id == "pi":
        if not model:
            raise ValueError("Pi needs --model so its temporary provider can be generated")
        if temp_dir is None:
            raise ValueError("Pi needs a temporary directory")
        api = {
            "anthropic": "anthropic-messages",
            "google": "google-generative-ai",
        }.get(provider, "openai-responses")
        key_env = {
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GEMINI_API_KEY",
            "xai": "XAI_API_KEY",
        }.get(provider, "OPENAI_API_KEY")
        model_config = {
            "providers": {
                "superqode": {
                    "baseUrl": base_v1 + "beta" if provider == "google" else base_v1,
                    "api": api,
                    # Pi requires an API key in its provider definition.  A
                    # non-secret sentinel is sufficient for the local hop;
                    # the gateway owns and injects the real upstream key.
                    "apiKey": "superqode-local-gateway" if provider == "google" else f"${key_env}",
                    "models": [{"id": model}],
                }
            }
        }
        settings = {"defaultProvider": "superqode", "defaultModel": model}
        env["PI_CODING_AGENT_DIR"] = str(temp_dir)
        files = {
            "models.json": json.dumps(model_config, indent=2) + "\n",
            "settings.json": json.dumps(settings, indent=2) + "\n",
        }
        note = profile.note
        if not current_env.get(key_env):
            note += f" {key_env} is not currently set."
        return LaunchPlan(
            profile,
            (executable, "--provider", "superqode", "--model", model, *args),
            env,
            files,
            note,
        )
    if profile.id == "superqode":
        env["SUPERQODE_TOOL_ROUTING"] = "shadow"
        return LaunchPlan(profile, (executable, *args), env)
    raise ValueError(profile.note or f"{profile.label} does not expose a supported endpoint hook")


def provider_upstream(provider: str) -> tuple[str, str]:
    return {
        "openai": ("https://api.openai.com", "OPENAI_API_KEY"),
        "anthropic": ("https://api.anthropic.com", "ANTHROPIC_API_KEY"),
        "google": (
            "https://generativelanguage.googleapis.com",
            "GEMINI_API_KEY",
        ),
        "xai": ("https://api.x.ai", "XAI_API_KEY"),
    }[provider]


__all__ = [
    "HarnessProfile",
    "LaunchPlan",
    "build_launch_plan",
    "get_profile",
    "profiles",
    "provider_upstream",
]
