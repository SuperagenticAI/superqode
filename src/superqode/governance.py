"""Layered contextual policy and host-bound credential brokering.

The governance layer is deliberately runtime-neutral.  It can explain a
decision without executing anything, while active harness runs use the same
engine at request, response, tool-call, tool-result, and promotion phases.
"""

from __future__ import annotations

import contextlib
import contextvars
import fnmatch
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import urlparse

import yaml


POLICY_PHASES = ("request", "response", "tool_call", "tool_result", "promotion")
POLICY_ACTIONS = ("allow", "ask", "deny")
ORG_POLICY_ENV = "SUPERQODE_ORG_POLICY"
PROJECT_POLICY_PATH = Path(".superqode/policy.yaml")
_SECRET_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "api-key", "x-auth-token"}
)


@dataclass(frozen=True)
class ContextualPolicyRule:
    """One matchable rule in a named policy layer."""

    rule_id: str
    action: str
    phases: tuple[str, ...] = ("tool_call",)
    tools: tuple[str, ...] = ("*",)
    tool_groups: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    runtimes: tuple[str, ...] = ()
    argument_patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    message: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, fallback_id: str) -> "ContextualPolicyRule":
        action = str(data.get("action") or "deny").strip().lower()
        if action not in POLICY_ACTIONS:
            raise ValueError(f"policy action must be one of: {', '.join(POLICY_ACTIONS)}")
        phases = _strings(data.get("phases") or data.get("phase") or ("tool_call",))
        invalid = sorted(set(phases) - set(POLICY_PHASES))
        if invalid:
            raise ValueError(f"unknown policy phase(s): {', '.join(invalid)}")
        raw_patterns = data.get("arguments") or data.get("argument_patterns") or {}
        if not isinstance(raw_patterns, Mapping):
            raise ValueError("policy rule arguments must be a mapping")
        return cls(
            rule_id=str(data.get("id") or fallback_id),
            action=action,
            phases=phases,
            tools=_strings(data.get("tools") or data.get("tool") or ("*",)),
            tool_groups=_strings(data.get("tool_groups") or ()),
            hosts=_strings(data.get("hosts") or data.get("host") or ()),
            risks=_strings(data.get("risks") or data.get("risk") or ()),
            providers=_strings(data.get("providers") or data.get("provider") or ()),
            runtimes=_strings(data.get("runtimes") or data.get("runtime") or ()),
            argument_patterns={str(key): _strings(value) for key, value in raw_patterns.items()},
            message=str(data.get("message") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyLayer:
    """Rules and defaults contributed by one ownership scope."""

    name: str
    source: str
    rules: tuple[ContextualPolicyRule, ...] = ()
    defaults: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "defaults": dict(self.defaults),
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True)
class PolicyRequest:
    """Normalized input evaluated by the contextual policy engine."""

    phase: str
    tool: str = ""
    tool_group: str = ""
    host: str = ""
    risk: str = ""
    provider: str = ""
    runtime: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyMatch:
    layer: str
    source: str
    rule_id: str
    action: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextualPolicyDecision:
    phase: str
    action: str
    reason: str
    matches: tuple[PolicyMatch, ...] = ()
    default_layer: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @property
    def enforced(self) -> bool:
        return bool(self.matches or self.default_layer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "action": self.action,
            "allowed": self.allowed,
            "enforced": self.enforced,
            "reason": self.reason,
            "default_layer": self.default_layer,
            "matches": [item.to_dict() for item in self.matches],
        }


class ContextualPolicyEngine:
    """Evaluate all matching layers with deny-overrides semantics."""

    def __init__(self, layers: Iterable[PolicyLayer] = ()) -> None:
        self.layers = tuple(layers)

    def evaluate(self, request: PolicyRequest) -> ContextualPolicyDecision:
        if request.phase not in POLICY_PHASES:
            raise ValueError(f"policy phase must be one of: {', '.join(POLICY_PHASES)}")
        matches: list[PolicyMatch] = []
        for layer in self.layers:
            for rule in layer.rules:
                if _rule_matches(rule, request):
                    matches.append(
                        PolicyMatch(
                            layer=layer.name,
                            source=layer.source,
                            rule_id=rule.rule_id,
                            action=rule.action,
                            message=rule.message,
                        )
                    )
        if matches:
            action = _strongest_action(item.action for item in matches)
            winners = [item for item in matches if item.action == action]
            reason = "; ".join(
                item.message or f"{item.layer}/{item.rule_id} returned {item.action}"
                for item in winners
            )
            return ContextualPolicyDecision(
                request.phase,
                action,
                reason,
                tuple(matches),
            )
        for layer in reversed(self.layers):
            action = layer.defaults.get(request.phase, "").strip().lower()
            if action:
                if action not in POLICY_ACTIONS:
                    raise ValueError(
                        f"policy default for {request.phase} must be one of: "
                        f"{', '.join(POLICY_ACTIONS)}"
                    )
                return ContextualPolicyDecision(
                    request.phase,
                    action,
                    f"{layer.name} default is {action}",
                    default_layer=layer.name,
                )
        return ContextualPolicyDecision(
            request.phase,
            "allow",
            "no contextual policy rule matched",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"layers": [layer.to_dict() for layer in self.layers]}


@dataclass(frozen=True)
class CredentialBinding:
    """A symbolic secret bound to explicit destination hosts."""

    name: str
    source: str
    hosts: tuple[str, ...]
    header: str = "Authorization"
    prefix: str = "Bearer"

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "CredentialBinding":
        source = str(data.get("source") or "").strip()
        hosts = _strings(data.get("hosts") or data.get("host") or ())
        if not source.startswith(("env:", "auth:")):
            raise ValueError(f"credential {name} source must use env: or auth:")
        if not hosts:
            raise ValueError(f"credential {name} must declare at least one host")
        return cls(
            name=name,
            source=source,
            hosts=hosts,
            header=str(data.get("header") or "Authorization"),
            prefix=str(data.get("prefix") or "Bearer"),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.split(":", 1)[0] + ":<redacted>",
            "hosts": list(self.hosts),
            "header": self.header,
            "prefix": self.prefix,
        }


class CredentialBroker:
    """Resolve credentials only at execution time and only for bound hosts."""

    def __init__(self, bindings: Iterable[CredentialBinding] = ()) -> None:
        self.bindings = {item.name: item for item in bindings}

    def inject(self, args: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        execution_args = dict(args)
        name = str(execution_args.pop("credential", "") or "").strip()
        if not name:
            return execution_args, {}
        binding = self.bindings.get(name)
        if binding is None:
            raise ValueError(f"unknown credential binding: {name}")
        url = str(execution_args.get("url") or "")
        host = (urlparse(url).hostname or "").lower()
        if not host or not any(_host_matches(host, pattern) for pattern in binding.hosts):
            raise ValueError(f"credential {name} is not permitted for host {host or '<unknown>'}")
        value = _resolve_credential(binding.source)
        if not value:
            raise ValueError(f"credential {name} is unavailable")
        headers = dict(execution_args.get("headers") or {})
        if any(key.lower() == binding.header.lower() for key in headers):
            raise ValueError(f"header {binding.header} is owned by credential binding {name}")
        headers[binding.header] = f"{binding.prefix} {value}".strip()
        execution_args["headers"] = headers
        return execution_args, {
            "credential": name,
            "host": host,
            "header": binding.header,
            "source": binding.source.split(":", 1)[0],
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {"bindings": [item.to_public_dict() for item in self.bindings.values()]}


@dataclass(frozen=True)
class GovernanceBundle:
    engine: ContextualPolicyEngine
    broker: CredentialBroker
    shell_env: str = "inherit"
    network_strict: bool = False
    allowed_hosts: tuple[str, ...] = ()
    block_model_credentials: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "policy": self.engine.to_dict(),
            "credentials": self.broker.to_public_dict(),
            "guardrails": {
                "shell_env": self.shell_env,
                "network_strict": self.network_strict,
                "allowed_hosts": list(self.allowed_hosts),
                "block_model_credentials": self.block_model_credentials,
            },
        }


_ACTIVE_BUNDLE: contextvars.ContextVar[GovernanceBundle | None] = contextvars.ContextVar(
    "superqode_governance_bundle", default=None
)


@contextlib.contextmanager
def governance_scope(bundle: GovernanceBundle) -> Iterator[None]:
    token = _ACTIVE_BUNDLE.set(bundle)
    try:
        yield
    finally:
        _ACTIVE_BUNDLE.reset(token)


def active_governance() -> GovernanceBundle | None:
    return _ACTIVE_BUNDLE.get()


def evaluate_active_policy(
    phase: str,
    *,
    tool: str = "",
    tool_group: str = "",
    host: str = "",
    risk: str = "",
    provider: str = "",
    runtime: str = "",
    arguments: Mapping[str, Any] | None = None,
) -> ContextualPolicyDecision:
    bundle = active_governance()
    request = PolicyRequest(
        phase=phase,
        tool=tool,
        tool_group=tool_group,
        host=host or _host_from_arguments(arguments or {}),
        risk=risk,
        provider=provider,
        runtime=runtime,
        arguments=dict(arguments or {}),
    )
    if bundle is None:
        return ContextualPolicyDecision(phase, "allow", "no active governance context")
    return bundle.engine.evaluate(request)


def load_governance(
    repository: str | Path,
    *,
    harness_spec: Any | None = None,
    work_order: Any | None = None,
    session_policy: Mapping[str, Any] | None = None,
    secure_defaults: bool = False,
) -> GovernanceBundle:
    """Load org → project → harness → WorkOrder → session policy layers."""
    root = Path(repository).expanduser().resolve()
    documents: list[tuple[str, str, dict[str, Any]]] = []
    org_path = os.environ.get(ORG_POLICY_ENV, "").strip()
    if org_path:
        path = Path(org_path).expanduser().resolve()
        documents.append(("organization", str(path), _load_policy_file(path)))
    project_path = root / PROJECT_POLICY_PATH
    if project_path.exists():
        documents.append(("project", str(project_path), _load_policy_file(project_path)))
    if harness_spec is not None:
        documents.append(
            (
                "harness",
                f"HarnessSpec:{getattr(harness_spec, 'name', 'unknown')}",
                _harness_policy(harness_spec),
            )
        )
    metadata = getattr(work_order, "metadata", {}) if work_order is not None else {}
    if isinstance(metadata, Mapping) and isinstance(metadata.get("governance"), Mapping):
        documents.append(
            ("work_order", f"WorkOrder:{work_order.work_order_id}", dict(metadata["governance"]))
        )
    if session_policy:
        documents.append(("session", "session", dict(session_policy)))

    layers: list[PolicyLayer] = []
    bindings: dict[str, CredentialBinding] = {}
    guardrails: dict[str, Any] = {}
    for layer_name, source, document in documents:
        layers.append(_policy_layer(layer_name, source, document))
        raw_bindings = document.get("credentials") or {}
        if not isinstance(raw_bindings, Mapping):
            raise ValueError(f"credentials in {source} must be a mapping")
        for name, binding in raw_bindings.items():
            if not isinstance(binding, Mapping):
                raise ValueError(f"credential {name} in {source} must be a mapping")
            bindings[str(name)] = CredentialBinding.from_dict(str(name), binding)
        raw_guardrails = document.get("guardrails") or {}
        if not isinstance(raw_guardrails, Mapping):
            raise ValueError(f"guardrails in {source} must be a mapping")
        guardrails.update(raw_guardrails)
    return GovernanceBundle(
        engine=ContextualPolicyEngine(layers),
        broker=CredentialBroker(bindings.values()),
        shell_env=str(
            guardrails.get("shell_env") or ("filter-secrets" if secure_defaults else "inherit")
        ),
        network_strict=bool(guardrails.get("network_strict", secure_defaults)),
        allowed_hosts=_strings(guardrails.get("allowed_hosts") or ()),
        block_model_credentials=bool(guardrails.get("block_model_credentials", True)),
    )


def default_project_policy() -> dict[str, Any]:
    """Secure builder defaults written by the policy initializer."""
    return {
        "version": 1,
        "defaults": {"request": "allow", "response": "allow", "tool_result": "allow"},
        "guardrails": {
            "shell_env": "filter-secrets",
            "network_strict": True,
            "allowed_hosts": [],
            "block_model_credentials": True,
        },
        "rules": [
            {
                "id": "deny-critical-tools",
                "phases": ["tool_call"],
                "action": "deny",
                "risks": ["critical"],
                "message": "critical tool calls are denied by project policy",
            }
        ],
        "credentials": {},
    }


def write_project_policy(repository: str | Path, *, force: bool = False) -> Path:
    path = Path(repository).expanduser().resolve() / PROJECT_POLICY_PATH
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(default_project_policy(), sort_keys=False), encoding="utf-8")
    return path


def model_supplied_secret_headers(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    headers = arguments.get("headers") or {}
    if not isinstance(headers, Mapping):
        return ()
    return tuple(sorted(str(key) for key in headers if str(key).lower() in _SECRET_HEADERS))


def _policy_layer(name: str, source: str, document: Mapping[str, Any]) -> PolicyLayer:
    raw_rules = document.get("rules") or ()
    if not isinstance(raw_rules, (list, tuple)):
        raise ValueError(f"rules in {source} must be a list")
    rules = tuple(
        ContextualPolicyRule.from_dict(item, fallback_id=f"rule-{index + 1}")
        for index, item in enumerate(raw_rules)
        if isinstance(item, Mapping)
    )
    raw_defaults = document.get("defaults") or {}
    if not isinstance(raw_defaults, Mapping):
        raise ValueError(f"defaults in {source} must be a mapping")
    defaults = {str(key): str(value).lower() for key, value in raw_defaults.items()}
    return PolicyLayer(name=name, source=source, rules=rules, defaults=defaults)


def _harness_policy(spec: Any) -> dict[str, Any]:
    execution = getattr(spec, "execution_policy", None)
    if execution is None:
        return {}
    rules = []
    for index, rule in enumerate(getattr(execution, "permission_rules", ())):
        pattern = str(getattr(rule, "pattern", "*") or "*")
        argument = str(getattr(rule, "argument", "") or "")
        rules.append(
            {
                "id": f"permission-{index + 1}",
                "phase": "tool_call",
                "action": str(getattr(rule, "action", "ask") or "ask"),
                "tool": str(getattr(rule, "tool", "*") or "*"),
                "arguments": {argument or "*": [pattern]},
            }
        )
    return {"rules": rules}


def _load_policy_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"governance policy does not exist: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"governance policy must be a mapping: {path}")
    version = int(payload.get("version") or 1)
    if version != 1:
        raise ValueError(f"unsupported governance policy version {version}: {path}")
    return payload


def _rule_matches(rule: ContextualPolicyRule, request: PolicyRequest) -> bool:
    if request.phase not in rule.phases:
        return False
    if rule.tools and not any(fnmatch.fnmatchcase(request.tool, pattern) for pattern in rule.tools):
        return False
    if rule.tool_groups and request.tool_group not in rule.tool_groups:
        return False
    if rule.hosts and not any(_host_matches(request.host, pattern) for pattern in rule.hosts):
        return False
    if rule.risks and request.risk not in rule.risks:
        return False
    if rule.providers and not any(
        fnmatch.fnmatchcase(request.provider, item) for item in rule.providers
    ):
        return False
    if rule.runtimes and not any(
        fnmatch.fnmatchcase(request.runtime, item) for item in rule.runtimes
    ):
        return False
    for argument, patterns in rule.argument_patterns.items():
        if argument == "*" and patterns == ("*",):
            continue
        values = (
            request.arguments.values() if argument == "*" else (request.arguments.get(argument),)
        )
        if not any(
            fnmatch.fnmatchcase(str(value), pattern)
            for value in values
            if value is not None
            for pattern in patterns
        ):
            return False
    return True


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return tuple(str(item) for item in value)
    return (str(value),)


def _strongest_action(actions: Iterable[str]) -> str:
    rank = {"allow": 0, "ask": 1, "deny": 2}
    return max(actions, key=rank.__getitem__)


def _host_matches(host: str, pattern: str) -> bool:
    host = host.lower().strip(".")
    pattern = pattern.lower().strip()
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host == suffix or host.endswith("." + suffix)
    return fnmatch.fnmatchcase(host, pattern)


def _host_from_arguments(arguments: Mapping[str, Any]) -> str:
    value = str(arguments.get("url") or arguments.get("host") or "")
    if "://" in value:
        return (urlparse(value).hostname or "").lower()
    return value.lower()


def _resolve_credential(source: str) -> str:
    kind, reference = source.split(":", 1)
    if kind == "env":
        return os.environ.get(reference, "")
    if kind == "auth":
        from superqode.auth import ApiAuth, OAuthAuth, WellKnownAuth, get

        auth = get(reference)
        if isinstance(auth, ApiAuth):
            return auth.key
        if isinstance(auth, OAuthAuth) and not auth.is_expired():
            return auth.access
        if isinstance(auth, WellKnownAuth):
            return auth.token or auth.key
    return ""


__all__ = [
    "ContextualPolicyDecision",
    "ContextualPolicyEngine",
    "ContextualPolicyRule",
    "CredentialBinding",
    "CredentialBroker",
    "GovernanceBundle",
    "ORG_POLICY_ENV",
    "POLICY_ACTIONS",
    "POLICY_PHASES",
    "PROJECT_POLICY_PATH",
    "PolicyLayer",
    "PolicyRequest",
    "active_governance",
    "default_project_policy",
    "evaluate_active_policy",
    "governance_scope",
    "load_governance",
    "model_supplied_secret_headers",
    "write_project_policy",
]
