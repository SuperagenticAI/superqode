"""Public Python extension API and runtime for the native SuperQode harness.

The native ``core`` harness deliberately starts with four tools.  Extensions
are the opt-in layer that can add tools, lifecycle hooks, slash commands,
context, permission rules, providers, and skills without changing SuperQode.

Python packages expose an :class:`Extension` through the
``superqode.extensions`` entry-point group::

    [project.entry-points."superqode.extensions"]
    company = "company_superqode:extension"

Project-local ``plugin.json`` manifests remain supported and are adapted to
the same runtime.  Executable project plugins load only after the project has
been trusted; installed Python entry points and user-level manifests are
explicit user installations and do not depend on project trust.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import inspect
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Sequence, get_args, get_origin, get_type_hints

from .agent.hooks import ALL_HOOK_POINTS, PERMISSION_REQUEST, HookRegistry
from .tools.base import Tool, ToolContext, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

EXTENSION_ENTRY_POINT_GROUP = "superqode.extensions"
EXTENSION_API_VERSION = 1
_EXTENSION_PROVIDER_OWNERS: dict[str, str] = {}


@dataclass(frozen=True)
class ExtensionCompatibility:
    """Compatibility contract declared by an extension."""

    api_version: int = EXTENSION_API_VERSION
    requires_superqode: str = ""


@dataclass(frozen=True)
class ExtensionLoadError:
    """One isolated extension contribution failure."""

    extension_id: str
    capability: str
    message: str
    source: str = ""


@dataclass(frozen=True)
class ToolContribution:
    factory: Callable[[], Tool]
    replace: bool = False


@dataclass(frozen=True)
class CommandContribution:
    name: str
    handler: Callable[..., Any]
    description: str = ""
    aliases: tuple[str, ...] = ()
    category: str = "extension"


@dataclass(frozen=True)
class HookContribution:
    point: str
    handler: Callable[..., Any]
    name: str = ""


@dataclass(frozen=True)
class ContextContribution:
    source: Callable[["ExtensionContext"], str]
    name: str = ""


@dataclass(frozen=True)
class ProviderContribution:
    provider: Any
    replace: bool = False


@dataclass(frozen=True)
class ExtensionContext:
    """Stable, deliberately small context passed to extension callbacks."""

    root: Path
    harness_id: str = "core"
    provider: str = ""
    model: str = ""
    session_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


class FunctionTool(Tool):
    """Adapt a typed Python function into the native Tool contract."""

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        read_only: bool = False,
    ) -> None:
        self._fn = fn
        self._name = (name or fn.__name__).strip()
        self._description = (description or inspect.getdoc(fn) or self._name).strip()
        self._parameters = dict(parameters or _schema_from_signature(fn))
        self.read_only = bool(read_only)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            result = _call_tool_function(self._fn, args, ctx)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 - extension code is isolated.
            logger.exception("Extension tool %s failed", self.name)
            return ToolResult(success=False, output="", error=str(exc))
        if isinstance(result, ToolResult):
            return result
        if result is None:
            output = ""
        elif isinstance(result, str):
            output = result
        elif isinstance(result, (dict, list, tuple, bool, int, float)):
            output = json.dumps(result, ensure_ascii=False, default=str)
        else:
            output = str(result)
        return ToolResult(success=True, output=output)


class Extension:
    """A Python-native collection of optional Core harness contributions."""

    def __init__(
        self,
        extension_id: str,
        *,
        name: str | None = None,
        version: str = "0.1.0",
        description: str = "",
        compatibility: ExtensionCompatibility | None = None,
    ) -> None:
        normalized = extension_id.strip()
        if not normalized:
            raise ValueError("extension id cannot be empty")
        self.id = normalized
        self.name = (name or normalized).strip()
        self.version = version.strip() or "0.1.0"
        self.description = description.strip()
        self.compatibility = compatibility or ExtensionCompatibility()
        self.tools: list[ToolContribution] = []
        self.commands: list[CommandContribution] = []
        self.hooks: list[HookContribution] = []
        self.context_sources: list[ContextContribution] = []
        self.permission_rules: list[dict[str, Any]] = []
        self.providers: list[ProviderContribution] = []
        self.skills: list[Path] = []
        self.source = "python"

    @property
    def capabilities(self) -> tuple[str, ...]:
        values: list[str] = []
        for name, contributions in (
            ("tools", self.tools),
            ("commands", self.commands),
            ("hooks", self.hooks),
            ("context", self.context_sources),
            ("permissions", self.permission_rules),
            ("providers", self.providers),
            ("skills", self.skills),
        ):
            if contributions:
                values.append(name)
        return tuple(values)

    def tool(
        self,
        value: Callable[..., Any] | type[Tool] | Tool | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        read_only: bool = False,
        replace: bool = False,
    ) -> Any:
        """Register a Tool instance/class or decorate a typed function."""

        def register(target: Callable[..., Any] | type[Tool] | Tool) -> Any:
            if isinstance(target, Tool):

                def factory(target: Tool = target) -> Tool:
                    return target
            elif inspect.isclass(target) and issubclass(target, Tool):
                factory = target
            elif callable(target):

                def factory(target: Callable[..., Any] = target) -> Tool:
                    return FunctionTool(
                        target,
                        name=name,
                        description=description,
                        parameters=parameters,
                        read_only=read_only,
                    )
            else:
                raise TypeError("extension.tool expects a Tool or callable")
            self.tools.append(ToolContribution(factory=factory, replace=replace))
            return target

        if value is None:
            return register
        return register(value)

    def command(
        self,
        name: str,
        *,
        description: str = "",
        aliases: Sequence[str] = (),
        category: str = "extension",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorate a slash-command handler."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.commands.append(
                CommandContribution(
                    name=_normalize_command_name(name),
                    handler=fn,
                    description=description or inspect.getdoc(fn) or "",
                    aliases=tuple(_normalize_command_name(alias) for alias in aliases),
                    category=category or "extension",
                )
            )
            return fn

        return decorator

    def hook(
        self, point: str, *, name: str = ""
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorate a lifecycle hook handler."""
        if point not in ALL_HOOK_POINTS:
            raise ValueError(f"unknown hook point {point!r}")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.append(HookContribution(point=point, handler=fn, name=name))
            return fn

        return decorator

    def before_tool(self, fn: Callable[..., Any] | None = None, *, name: str = "") -> Any:
        """Register or decorate a ``before_tool_call`` hook."""
        decorator = self.hook("before_tool_call", name=name)
        return decorator(fn) if fn is not None else decorator

    def context(
        self,
        fn: Callable[[ExtensionContext], str] | None = None,
        *,
        name: str = "",
    ) -> Any:
        """Register or decorate a synchronous, bounded context source."""

        def decorator(source: Callable[[ExtensionContext], str]) -> Callable[..., Any]:
            self.context_sources.append(ContextContribution(source=source, name=name))
            return source

        return decorator(fn) if fn is not None else decorator

    def permission(self, **rule: Any) -> None:
        """Add a declarative tool permission rule."""
        self.permission_rules.append(dict(rule))

    def provider(self, provider: Any, *, replace: bool = False) -> Any:
        """Register a ProviderDef contribution."""
        self.providers.append(ProviderContribution(provider=provider, replace=replace))
        return provider

    def skill(self, path: str | Path) -> None:
        """Register a Markdown skill path supplied by the extension package."""
        self.skills.append(Path(path).expanduser())


@dataclass
class ExtensionRuntime:
    """Loaded extensions and their isolated activation results."""

    root: Path
    extensions: list[Extension] = field(default_factory=list)
    errors: list[ExtensionLoadError] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    _commands: dict[str, tuple[Extension, CommandContribution]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve()
        for extension in self.extensions:
            for command in extension.commands:
                for command_name in (command.name, *command.aliases):
                    if command_name in self._commands:
                        self.errors.append(
                            ExtensionLoadError(
                                extension.id,
                                "commands",
                                f"command {command_name!r} already registered",
                                extension.source,
                            )
                        )
                        continue
                    self._commands[command_name] = (extension, command)

    @property
    def active(self) -> bool:
        return bool(self.extensions)

    @property
    def commands(self) -> Mapping[str, CommandContribution]:
        return {name: item[1] for name, item in self._commands.items()}

    def apply_tools(self, registry: ToolRegistry) -> None:
        """Add extension tools without replacing built-ins unless explicit."""
        for extension in self.extensions:
            for contribution in extension.tools:
                try:
                    tool = contribution.factory()
                    if not isinstance(tool, Tool):
                        raise TypeError("tool factory did not return a Tool")
                    existing = registry.get(tool.name)
                    if existing is not None and not contribution.replace:
                        raise ValueError(
                            f"tool {tool.name!r} already exists; declare replace=True to override"
                        )
                    registry.register(tool)
                except Exception as exc:  # noqa: BLE001 - isolate extensions.
                    self._error(extension, "tools", exc)
        skill_paths = [path for extension in self.extensions for path in extension.skills]
        if skill_paths and registry.get("skill") is None:
            try:
                from .skills import SkillsLoader
                from .tools.skill_tools import SkillTool

                registry.register(SkillTool(SkillsLoader(self.root, extra_paths=skill_paths)))
            except Exception as exc:  # noqa: BLE001
                # Attribute this shared adapter failure to the first extension
                # that asked for the capability; other contributions still run.
                owner = next(extension for extension in self.extensions if extension.skills)
                self._error(owner, "skills", exc)

    def build_hooks(self, registry: HookRegistry | None = None) -> HookRegistry:
        """Register hook and permission contributions into one registry."""
        target = registry or HookRegistry()
        for extension in self.extensions:
            if extension.permission_rules:
                try:
                    from .harness.permissions import build_permission_handler
                    from .harness.spec import PermissionRuleSpec

                    rules = tuple(
                        PermissionRuleSpec(
                            tool=str(rule.get("tool") or "*"),
                            pattern=str(rule.get("pattern") or "*"),
                            action=str(rule.get("action") or "ask"),
                            argument=str(rule.get("argument") or ""),
                        )
                        for rule in extension.permission_rules
                    )
                    target.register(
                        PERMISSION_REQUEST,
                        build_permission_handler(rules),
                        name=f"extension:{extension.id}:permissions",
                    )
                except Exception as exc:  # noqa: BLE001
                    self._error(extension, "permissions", exc)
            for hook in extension.hooks:
                try:
                    target.register(
                        hook.point,
                        hook.handler,
                        name=hook.name or f"extension:{extension.id}:{hook.point}",
                    )
                except Exception as exc:  # noqa: BLE001
                    self._error(extension, "hooks", exc)
        return target

    def context_text(self, context: ExtensionContext, *, max_chars: int = 16_000) -> str:
        """Collect bounded context contributions in deterministic order."""
        parts: list[str] = []
        remaining = max(0, int(max_chars))
        for extension in self.extensions:
            for contribution in extension.context_sources:
                if remaining <= 0:
                    break
                try:
                    value = contribution.source(context)
                    if inspect.isawaitable(value):
                        raise TypeError("context sources must be synchronous")
                    text = str(value or "").strip()
                    if not text:
                        continue
                    text = text[:remaining]
                    parts.append(f"# Extension: {extension.name}\n\n{text}")
                    remaining -= len(text)
                except Exception as exc:  # noqa: BLE001
                    self._error(extension, "context", exc)
        return "\n\n".join(parts)

    def apply_providers(self) -> None:
        """Install ProviderDef contributions into the process provider catalog."""
        from .providers.registry import PROVIDERS, ProviderDef

        for extension in self.extensions:
            for contribution in extension.providers:
                try:
                    provider = contribution.provider
                    if not isinstance(provider, ProviderDef):
                        raise TypeError("provider contribution must be ProviderDef")
                    owner = _EXTENSION_PROVIDER_OWNERS.get(provider.id)
                    if (
                        provider.id in PROVIDERS
                        and owner != extension.id
                        and not contribution.replace
                    ):
                        raise ValueError(
                            f"provider {provider.id!r} already exists; use replace=True to override"
                        )
                    PROVIDERS[provider.id] = provider
                    _EXTENSION_PROVIDER_OWNERS[provider.id] = extension.id
                except Exception as exc:  # noqa: BLE001
                    self._error(extension, "providers", exc)

    async def invoke_command(
        self,
        name: str,
        args: str = "",
        *,
        context: ExtensionContext | None = None,
    ) -> Any:
        """Invoke a registered extension slash command."""
        item = self._commands.get(_normalize_command_name(name))
        if item is None:
            raise KeyError(name)
        extension, command = item
        command_context = context or ExtensionContext(root=self.root)
        try:
            result = _call_command(command.handler, args, command_context)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:  # noqa: BLE001
            self._error(extension, "commands", exc)
            raise

    def _error(self, extension: Extension, capability: str, exc: Exception) -> None:
        error = ExtensionLoadError(extension.id, capability, str(exc), extension.source)
        if error not in self.errors:
            self.errors.append(error)
        logger.warning("extension %s %s contribution failed: %s", extension.id, capability, exc)


def load_extension_runtime(
    root: str | Path = ".",
    *,
    include_entry_points: bool = True,
    include_manifests: bool = True,
) -> ExtensionRuntime:
    """Discover extensions with per-extension compatibility and failure isolation."""
    project_root = Path(root).expanduser().resolve()
    extensions: list[Extension] = []
    errors: list[ExtensionLoadError] = []
    skipped: list[str] = []
    from .plugins import disabled_plugin_ids

    disabled = disabled_plugin_ids(project_root)

    if include_entry_points:
        for entry_point in _extension_entry_points():
            if entry_point.name in disabled:
                skipped.append(f"{entry_point.name}: disabled")
                continue
            try:
                loaded = entry_point.load()
                extension = _coerce_extension(loaded)
                extension.source = f"entry-point:{entry_point.name}"
                if extension.id in disabled:
                    skipped.append(f"{extension.id}: disabled")
                    continue
                _check_compatibility(extension)
                extensions.append(extension)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    ExtensionLoadError(
                        entry_point.name,
                        "load",
                        str(exc),
                        f"entry-point:{entry_point.name}",
                    )
                )

    if include_manifests:
        from .plugins import (
            discover_plugin_manifests,
            load_plugin_manifest,
        )
        from .project_trust import is_project_trusted

        trusted = is_project_trusted(project_root)
        for manifest_path in discover_plugin_manifests(project_root):
            try:
                manifest = load_plugin_manifest(manifest_path)
                if manifest.id in disabled:
                    skipped.append(f"{manifest.id}: disabled")
                    continue
                if _is_project_manifest(manifest_path, project_root) and not trusted:
                    skipped.append(f"{manifest.id}: project is untrusted")
                    continue
                extension = _extension_from_manifest(manifest)
                _check_compatibility(extension)
                extensions.append(extension)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    ExtensionLoadError(
                        manifest_path.stem,
                        "load",
                        str(exc),
                        str(manifest_path),
                    )
                )

    runtime = ExtensionRuntime(
        root=project_root,
        extensions=_deduplicate_extensions(extensions, errors),
        errors=errors,
        skipped=skipped,
    )
    runtime.apply_providers()
    return runtime


def _extension_entry_points() -> list[Any]:
    points = importlib.metadata.entry_points()
    if hasattr(points, "select"):
        return list(points.select(group=EXTENSION_ENTRY_POINT_GROUP))
    return list(points.get(EXTENSION_ENTRY_POINT_GROUP, ()))


def _coerce_extension(value: Any) -> Extension:
    if isinstance(value, Extension):
        return value
    if callable(value):
        value = value()
        if isinstance(value, Extension):
            return value
    extension = getattr(value, "extension", None)
    if isinstance(extension, Extension):
        return extension
    raise TypeError("entry point must expose an Extension or a zero-argument Extension factory")


def _check_compatibility(extension: Extension) -> None:
    if extension.compatibility.api_version != EXTENSION_API_VERSION:
        raise ValueError(
            f"extension API {extension.compatibility.api_version} is incompatible with "
            f"SuperQode API {EXTENSION_API_VERSION}"
        )
    requirement = extension.compatibility.requires_superqode.strip()
    if requirement and not _version_satisfies(_superqode_version(), requirement):
        raise ValueError(
            f"requires SuperQode {requirement}; installed version is {_superqode_version()}"
        )


def _superqode_version() -> str:
    try:
        return importlib.metadata.version("superqode")
    except importlib.metadata.PackageNotFoundError:
        from . import __version__

        return __version__


def _version_satisfies(version: str, requirement: str) -> bool:
    """Small dependency-free checker for comma-separated comparison clauses."""
    current = _version_tuple(version)
    for clause in (item.strip() for item in requirement.split(",")):
        if not clause:
            continue
        match = re.fullmatch(r"(>=|<=|==|!=|>|<)?\s*([0-9]+(?:\.[0-9]+){0,3})", clause)
        if not match:
            raise ValueError(f"unsupported requires_superqode clause: {clause!r}")
        operator, expected_text = match.groups()
        expected = _version_tuple(expected_text)
        size = max(len(current), len(expected))
        left = current + (0,) * (size - len(current))
        right = expected + (0,) * (size - len(expected))
        operator = operator or "=="
        satisfied = {
            "==": left == right,
            "!=": left != right,
            ">=": left >= right,
            "<=": left <= right,
            ">": left > right,
            "<": left < right,
        }[operator]
        if not satisfied:
            return False
    return True


def _version_tuple(value: str) -> tuple[int, ...]:
    numbers = re.match(r"\d+(?:\.\d+)*", value.strip())
    if not numbers:
        return (0,)
    return tuple(int(item) for item in numbers.group(0).split("."))


def _deduplicate_extensions(
    extensions: Iterable[Extension], errors: list[ExtensionLoadError]
) -> list[Extension]:
    out: list[Extension] = []
    seen: set[str] = set()
    for extension in extensions:
        if extension.id in seen:
            errors.append(
                ExtensionLoadError(
                    extension.id,
                    "load",
                    "duplicate extension id; first discovered extension wins",
                    extension.source,
                )
            )
            continue
        seen.add(extension.id)
        out.append(extension)
    return out


def _is_project_manifest(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return any(
        _is_relative_to(resolved, directory)
        for directory in (root / ".superqode" / "plugins", root / ".agents" / "plugins")
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _extension_from_manifest(manifest: Any) -> Extension:
    extension = Extension(
        manifest.id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        compatibility=ExtensionCompatibility(
            api_version=int(getattr(manifest, "api_version", EXTENSION_API_VERSION)),
            requires_superqode=str(getattr(manifest, "requires_superqode", "")),
        ),
    )
    extension.source = str(manifest.path or f"manifest:{manifest.id}")
    base = manifest.path.parent if manifest.path else Path.cwd()
    _ensure_import_path(base)

    for entry in manifest.tools:
        try:
            target = _manifest_target(entry, base, kind="tool")
            replace = bool(entry.get("replace", False))
            if isinstance(target, Tool):
                extension.tool(target, replace=replace)
            elif inspect.isclass(target) and issubclass(target, Tool):
                extension.tool(target, replace=replace)
            elif callable(target):
                extension.tool(
                    target,
                    name=str(entry.get("name") or "") or None,
                    description=str(entry.get("description") or "") or None,
                    parameters=entry.get("parameters"),
                    read_only=bool(entry.get("read_only", False)),
                    replace=replace,
                )
            else:
                raise TypeError("tool target is not a Tool or callable")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"tools entry failed: {exc}") from exc

    for entry in manifest.commands:
        target = _manifest_target(entry, base, kind="command")
        extension.commands.append(
            CommandContribution(
                name=_normalize_command_name(
                    str(entry.get("name") or getattr(target, "__name__", ""))
                ),
                handler=target,
                description=str(entry.get("description") or inspect.getdoc(target) or ""),
                aliases=tuple(str(item) for item in entry.get("aliases", ())),
                category=str(entry.get("category") or "extension"),
            )
        )

    for entry in manifest.event_hooks:
        if not isinstance(entry, dict):
            raise ValueError("event hook entry must be an object")
        point = str(entry.get("point") or "")
        target = _resolve_import_target(str(entry.get("handler") or entry.get("target") or ""))
        extension.hooks.append(
            HookContribution(point=point, handler=target, name=str(entry.get("name") or ""))
        )

    extension.permission_rules.extend(dict(item) for item in manifest.permission_rules)

    for entry in manifest.context_injectors:
        if not isinstance(entry, dict):
            raise ValueError("context injector entry must be an object")
        if entry.get("handler") or entry.get("target"):
            source = _resolve_import_target(str(entry.get("handler") or entry.get("target")))
        else:
            path = _resolve_manifest_path(base, str(entry.get("path") or ""))

            def source(_context: ExtensionContext, path: Path = path) -> str:
                return path.read_text(encoding="utf-8")

        extension.context_sources.append(
            ContextContribution(source=source, name=str(entry.get("name") or ""))
        )

    for entry in manifest.providers:
        target = _manifest_target(entry, base, kind="provider")
        if callable(target) and not _is_provider_def(target):
            target = target()
        extension.providers.append(
            ProviderContribution(provider=target, replace=bool(entry.get("replace", False)))
        )

    for skill in manifest.skills:
        extension.skills.append(_resolve_manifest_path(base, str(skill)))
    return extension


def _manifest_target(entry: Any, base: Path, *, kind: str) -> Any:
    if not isinstance(entry, dict):
        raise TypeError(f"{kind} entry must be an object")
    import_target = entry.get("handler") or entry.get("target") or entry.get("class")
    path_text = str(entry.get("path") or "").strip()
    if import_target and not path_text:
        return _resolve_import_target(str(import_target))
    if not path_text:
        raise ValueError(f"{kind} entry requires path, handler, or target")
    path = _resolve_manifest_path(base, path_text)
    module = _load_file_module(path)
    if import_target:
        attr = str(import_target).split(":")[-1].split(".")[-1]
        return getattr(module, attr)
    name = str(entry.get("name") or "").strip()
    candidates: list[str] = []
    if name:
        camel = "".join(part.capitalize() for part in re.split(r"[-_]", name) if part)
        candidates.extend([f"{camel}Tool", camel, name])
    candidates.extend([kind, kind.capitalize(), kind.upper()])
    for candidate in candidates:
        if hasattr(module, candidate):
            return getattr(module, candidate)
    values = [
        value
        for value in vars(module).values()
        if (
            (
                kind == "tool"
                and inspect.isclass(value)
                and issubclass(value, Tool)
                and value is not Tool
            )
            or (kind == "provider" and _is_provider_def(value))
        )
    ]
    if len(values) == 1:
        return values[0]
    callables = [
        value
        for key, value in vars(module).items()
        if not key.startswith("_")
        and callable(value)
        and getattr(value, "__module__", "") == module.__name__
    ]
    if len(callables) == 1:
        return callables[0]
    raise ValueError(f"cannot determine {kind} target in {path}")


def _is_provider_def(value: Any) -> bool:
    from .providers.registry import ProviderDef

    return isinstance(value, ProviderDef)


def _resolve_manifest_path(base: Path, value: str) -> Path:
    if not value.strip():
        raise ValueError("path cannot be empty")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def _ensure_import_path(path: Path) -> None:
    text = str(path.resolve())
    if text not in sys.path:
        sys.path.insert(0, text)


def _load_file_module(path: Path) -> ModuleType:
    if path.suffix != ".py":
        raise ValueError(f"Python contribution must reference a .py file: {path}")
    module_name = f"_superqode_extension_{abs(hash(str(path.resolve())))}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import extension module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _resolve_import_target(spec: str) -> Any:
    from .plugins import _resolve_handler

    return _resolve_handler(spec)


def _normalize_command_name(value: str) -> str:
    return value.strip().lower().lstrip(":/")


def _call_command(fn: Callable[..., Any], args: str, context: ExtensionContext) -> Any:
    signature = inspect.signature(fn)
    parameters = list(signature.parameters.values())
    if not parameters:
        return fn()
    if len(parameters) == 1:
        if parameters[0].name in {"context", "ctx"}:
            return fn(context)
        return fn(args)
    return fn(args, context)


def _call_tool_function(fn: Callable[..., Any], args: dict[str, Any], ctx: ToolContext) -> Any:
    signature = inspect.signature(fn)
    parameters = list(signature.parameters.values())
    if len(parameters) == 2 and parameters[0].name in {"args", "arguments"}:
        return fn(args, ctx)
    kwargs = dict(args)
    for parameter in parameters:
        if parameter.name in {"ctx", "context", "tool_context"}:
            kwargs[parameter.name] = ctx
    return fn(**kwargs)


def _schema_from_signature(fn: Callable[..., Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    try:
        annotations = get_type_hints(fn)
    except Exception:  # noqa: BLE001 - unresolved forward refs degrade to open schemas.
        annotations = {}
    for parameter in inspect.signature(fn).parameters.values():
        if parameter.name in {"ctx", "context", "tool_context"}:
            continue
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        properties[parameter.name] = _annotation_schema(
            annotations.get(parameter.name, parameter.annotation)
        )
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
        else:
            properties[parameter.name]["default"] = parameter.default
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (list, Sequence, tuple):
        return {"type": "array", "items": _annotation_schema(args[0]) if args else {}}
    if origin in (dict, Mapping):
        return {"type": "object"}
    if origin is not None and type(None) in args:
        non_null = [item for item in args if item is not type(None)]
        schema = _annotation_schema(non_null[0]) if len(non_null) == 1 else {}
        return {"anyOf": [schema, {"type": "null"}]}
    primitive = {str: "string", int: "integer", float: "number", bool: "boolean"}.get(annotation)
    return {"type": primitive} if primitive else {}


__all__ = [
    "EXTENSION_API_VERSION",
    "EXTENSION_ENTRY_POINT_GROUP",
    "CommandContribution",
    "Extension",
    "ExtensionCompatibility",
    "ExtensionContext",
    "ExtensionLoadError",
    "ExtensionRuntime",
    "FunctionTool",
    "load_extension_runtime",
]
