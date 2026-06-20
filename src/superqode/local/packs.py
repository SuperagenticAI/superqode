"""Model policy packs: tuned defaults per open-model family, shipped as data.

A pack is one YAML file naming a model family, the substrings that identify
it, and the policy knobs that make it behave well in an agent loop (prompt
level, tool-call format, temperature, history budget). Packs ship in
``data/model-packs/`` and users can add or replace them by dropping files in
``~/.superqode/model-packs/`` (same schema; a file with the same ``name``
wins).

Harness specs reference a pack with ``model_policy.pack: gemma4``; without
an explicit reference the pack is auto-detected from the model id.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SHIPPED_PACKS_DIR = Path(__file__).parent / "data" / "model-packs"
USER_PACKS_DIR = Path.home() / ".superqode" / "model-packs"


@dataclass(frozen=True)
class ModelPack:
    name: str
    description: str = ""
    match: tuple = ()
    policy: Dict[str, Any] = field(default_factory=dict)
    notes: tuple = ()


@dataclass(frozen=True)
class PackDraft:
    """A generated user-editable model policy pack."""

    pack: ModelPack
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.pack.name,
            "description": self.pack.description,
            "match": list(self.pack.match),
            "policy": dict(self.pack.policy),
            "notes": list(self.pack.notes),
            **({"path": str(self.path)} if self.path else {}),
        }


def _load_pack_file(path: Path) -> Optional[ModelPack]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("name"):
        return None
    policy = data.get("policy")
    return ModelPack(
        name=str(data["name"]).strip().lower(),
        description=str(data.get("description", "")),
        match=tuple(str(m).lower() for m in data.get("match", [])),
        policy=dict(policy) if isinstance(policy, dict) else {},
        notes=tuple(str(n) for n in data.get("notes", [])),
    )


def load_packs() -> Dict[str, ModelPack]:
    """All packs by name; user packs override shipped packs with the same name."""
    packs: Dict[str, ModelPack] = {}
    for directory in (SHIPPED_PACKS_DIR, USER_PACKS_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            pack = _load_pack_file(path)
            if pack is not None:
                packs[pack.name] = pack
    return packs


def get_pack(name: str) -> Optional[ModelPack]:
    return load_packs().get(name.strip().lower())


def detect_pack(model_text: str) -> Optional[ModelPack]:
    """The pack whose match substrings appear in a model/provider string.

    Longest match wins so "qwen3-coder" beats "qwen3".
    """
    normalized = model_text.replace("_", "-").lower()
    best: Optional[ModelPack] = None
    best_len = 0
    for pack in load_packs().values():
        for needle in pack.match:
            if needle in normalized and len(needle) > best_len:
                best = pack
                best_len = len(needle)
    return best


def list_packs() -> List[ModelPack]:
    return sorted(load_packs().values(), key=lambda p: p.name)


def draft_pack(
    *,
    name: str = "",
    model: str = "",
    endpoint: str = "",
    from_smoke: str | Path | None = None,
) -> PackDraft:
    """Build a pack draft without probing any live endpoint.

    ``from_smoke`` accepts a saved ``superqode local smoke --json`` payload and
    uses its observed warnings/checks to choose conservative defaults.
    """
    smoke = _load_smoke_payload(from_smoke) if from_smoke else {}
    smoke_model = str(smoke.get("model") or "")
    smoke_endpoint = str(smoke.get("endpoint") or "")
    target_model = model or smoke_model
    target_endpoint = endpoint or smoke_endpoint
    pack_name = _pack_name(name or target_model or target_endpoint or "local-model")
    match = _match_terms(pack_name, target_model, target_endpoint)
    policy = _draft_policy(pack_name, target_model, smoke)
    notes = _draft_notes(target_model, target_endpoint, smoke)

    return PackDraft(
        pack=ModelPack(
            name=pack_name,
            description=_description(pack_name, target_model),
            match=tuple(match),
            policy=policy,
            notes=tuple(notes),
        )
    )


def write_pack_draft(
    draft: PackDraft,
    *,
    output: str | Path | None = None,
    force: bool = False,
) -> PackDraft:
    """Write a pack draft to YAML and return it with the target path."""
    import yaml

    target = Path(output).expanduser() if output else USER_PACKS_DIR / f"{draft.pack.name}.yaml"
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": draft.pack.name,
        "description": draft.pack.description,
        "match": list(draft.pack.match),
        "policy": dict(draft.pack.policy),
        "notes": list(draft.pack.notes),
    }
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return PackDraft(pack=draft.pack, path=target)


def render_pack_draft(draft: PackDraft) -> str:
    lines = ["SuperQode model pack draft", ""]
    lines.append(f"Name        {draft.pack.name}")
    lines.append(f"Matches     {', '.join(draft.pack.match)}")
    if draft.path:
        lines.append(f"Path        {draft.path}")
    lines.append("")
    lines.append("Policy")
    for key, value in draft.pack.policy.items():
        lines.append(f"  {key}: {value}")
    if draft.pack.notes:
        lines.append("")
        lines.append("Notes")
        for note in draft.pack.notes:
            lines.append(f"  - {note}")
    lines.append("")
    lines.append("Use this pack from a harness with:")
    lines.append("  model_policy:")
    lines.append(f"    pack: {draft.pack.name}")
    return "\n".join(lines)


def _load_smoke_payload(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _pack_name(value: str) -> str:
    raw = value.split("/")[-1].split(":")[0].strip().lower()
    raw = raw.replace("_", "-")
    raw = re.sub(r"[^a-z0-9.-]+", "-", raw).strip("-.")
    raw = re.sub(r"-+", "-", raw)
    return raw or "local-model"


def _match_terms(pack_name: str, model: str, endpoint: str) -> list[str]:
    terms = [pack_name]
    if model:
        lowered = model.replace("_", "-").lower()
        terms.append(lowered)
        terms.append(lowered.split("/")[-1])
        terms.append(lowered.split("/")[-1].split(":")[0])
    if endpoint:
        host = endpoint.replace("https://", "").replace("http://", "").split("/", 1)[0].lower()
        if host and "localhost" not in host and "127.0.0.1" not in host:
            terms.append(host)
    return list(dict.fromkeys(term.strip("-") for term in terms if term.strip("-")))


def _draft_policy(pack_name: str, model: str, smoke: dict[str, Any]) -> dict[str, Any]:
    checks = {
        str(item.get("name")): bool(item.get("ok"))
        for item in smoke.get("checks", [])
        if isinstance(item, dict) and item.get("name")
    }
    warnings = " ".join(str(item).lower() for item in smoke.get("warnings", []))
    policy: dict[str, Any] = {
        "temperature": 0.2,
        "parallel_tools": False,
        "session_history_limit": 12,
    }
    lowered = f"{pack_name} {model}".lower()
    if any(token in lowered for token in ("coder", "code", "devstral")):
        policy["temperature"] = 0.1
        policy["session_history_limit"] = 16
    if any(token in lowered for token in ("minimax", "gpt-oss", "reason", "r1", "thinking")):
        policy["reasoning"] = "medium"
        policy["session_history_limit"] = 16
    if "native tool calls look unreliable" in warnings or checks.get("read_file_tool") is False:
        policy["tool_call_format"] = "prompt"
    if checks.get("context_recall") is False:
        policy["session_history_limit"] = min(int(policy["session_history_limit"]), 8)
    return policy


def _draft_notes(model: str, endpoint: str, smoke: dict[str, Any]) -> list[str]:
    notes = [
        "Generated by `superqode local pack init`; review and commit this pack with your harness if it is project policy.",
        "Run `superqode local smoke` and held-out harness evals before broad write/shell use.",
    ]
    if model:
        notes.append(f"Target model: {model}")
    if endpoint:
        notes.append(f"Target endpoint: {endpoint}")
    if smoke.get("context_window"):
        notes.append(
            f"Smoke detected context window: {smoke['context_window']} ({smoke.get('context_source') or 'unknown source'})."
        )
    for warning in smoke.get("warnings", []):
        notes.append(f"Smoke warning: {warning}")
    return notes


def _description(pack_name: str, model: str) -> str:
    target = model or pack_name
    return f"Project-owned local model pack for {target}"


__all__ = [
    "ModelPack",
    "PackDraft",
    "SHIPPED_PACKS_DIR",
    "USER_PACKS_DIR",
    "detect_pack",
    "draft_pack",
    "get_pack",
    "list_packs",
    "load_packs",
    "render_pack_draft",
    "write_pack_draft",
]
