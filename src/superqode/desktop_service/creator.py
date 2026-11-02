"""Super Agent drafts.

A sentence becomes a reviewed HarnessSpec, a next-prompt preview, a skill
note, a WorkOrder program note, a panel layout, and a pure-Python check.
Nothing is written or enabled until the person saves the reviewed draft.
The Python check runs only in Monty. It prints a template. It is never
installed, and it is not connected to an RLM subcall or a child session.
"""

from __future__ import annotations

import ast
import json
import re

import yaml

from superqode.harness.loader import harness_spec_to_dict
from superqode.harness.spec import (
    AgentSpec,
    ExecutionPolicySpec,
    HarnessFlavor,
    HarnessSpec,
    RuntimeSpec,
)

from .studio import inspect as inspect_definition
from .studio import name, reviewed, save, within

PANELS = (
    "Workspace",
    "Review",
    "Files",
    "Terminal",
    "Threads",
    "Tools",
    "Evaluations",
    "Optimization",
    "Checkpoints",
    "Harness Studio",
)
ALWAYS = ("Workspace", "Review", "Files", "Terminal", "Tools")
KEYWORDS = (
    ("gauge", "Tools"),
    ("factory", "Tools"),
    ("rlm", "Tools"),
    ("recursive", "Tools"),
    ("eval", "Evaluations"),
    ("optimi", "Optimization"),
    ("checkpoint", "Checkpoints"),
    ("terminal", "Terminal"),
    ("review", "Review"),
    ("studio", "Harness Studio"),
    ("thread", "Threads"),
)


def slugify(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    body = "-".join(words[:4]).strip("-")
    if not body or not body[0].isalpha():
        body = ("repo-" + body).strip("-")
    body = body[:64].strip("-")
    return body if body and body[0].isalpha() else "repository"


def panels_for(description: str) -> list[str]:
    lowered = description.lower()
    chosen = list(ALWAYS)
    for word, panel in KEYWORDS:
        if word in lowered and panel not in chosen:
            chosen.append(panel)
    return [panel for panel in chosen if panel in PANELS]


def _bundle(description: str, slug: str) -> dict:
    spec = HarnessSpec(
        name=slug,
        description=description,
        flavor=HarnessFlavor.CODING,
        runtime=RuntimeSpec(backend="builtin"),
        execution_policy=ExecutionPolicySpec(
            sandbox="local",
            approval_profile="careful",
            allow_read=True,
            allow_write=True,
            allow_shell=True,
            allow_network=False,
            config={
                "default_permission": "ask",
                "group_permissions": {
                    "read": "allow",
                    "search": "allow",
                    "diagnostics": "allow",
                    "write": "ask",
                    "shell": "ask",
                    "network": "deny",
                    "agent": "ask",
                },
            },
        ),
        agents=(
            AgentSpec(
                id="coder",
                role="implementation",
                tools=("read", "write", "edit", "bash"),
                system_prompt=(
                    "You are a coding agent for this repository. This harness is a reviewed preview. "
                    "It uses the builtin runtime and the ordinary read, write, edit, and bash tools. "
                    "It does not start subcalls or child agents. "
                    "Stay inside the project, keep the network closed, and stop for review when a diff is ready. "
                    "Do not widen your tools or limits.\n\nWorkflow:\n" + description
                ),
            ),
        ),
        metadata={"creator": "super-agent", "preview": True, "writes_next_prompt": False},
    )
    text = yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False)
    skill = f"# {slug}\n\nThis skill is a draft. It does not run by itself.\n\n{description}\n"
    program = (
        f"# Work program · {slug}\n\n"
        "This note is a draft for a WorkOrder. It does not start work.\n\n"
        "1. Read the repository and restate the task.\n"
        "2. Do the work in an isolated copy when another task is active.\n"
        "3. Run the project's narrowest useful check.\n"
        "4. Stop for a person to review the diff.\n\n"
        f"Requested workflow:\n\n{description}\n"
    )
    layout = {"name": slug, "panels": panels_for(description)}
    recursion = _recursion(description)
    plugin = _plugin(description)
    return {
        "name": slug,
        "yaml": text,
        "skill": skill,
        "program": program,
        "recursion": recursion,
        "plugin": plugin,
        "panels": layout["panels"],
        "layout_digest": _digest(layout),
        "layout": layout,
    }


def _recursion(description: str) -> str:
    return (
        "# Who writes the next prompt\n\n"
        "This note is a preview. It is not connected to a recursive run.\n\n"
        "The person still writes the prompt for each turn. "
        "A later connection can hand the next prompt to an RLM subcall or a child session. "
        "That connection is not in this draft.\n\n"
        "The Monty check prints a templated next-prompt sentence. It does not call a model, "
        "and it cannot touch the host filesystem or network.\n\n"
        f"Task:\n\n{description}\n"
    )


def _plugin(description: str) -> str:
    """Pure Python. The task is data, so it cannot close the string and add a statement."""
    literal = json.dumps(description)
    return (
        "# Preview only. This prints a templated next prompt. "
        "It does not call a model or start a child session.\n"
        f"TASK = {literal}\n"
        "MAX_DEPTH = 3\n"
        "\n"
        "def next_prompt(goal, finding=''):\n"
        "    if not finding:\n"
        "        return 'Inspect the repository. Restate the task and the constraints. Task: ' + goal\n"
        "    return 'Write the next bounded step from this finding. Stay inside the task. Task: ' + goal\n"
        "\n"
        "def stop(depth, ready_for_review):\n"
        "    return depth >= MAX_DEPTH or bool(ready_for_review)\n"
        "\n"
        "print(next_prompt(TASK))\n"
        "print(stop(1, False))\n"
    )


def pure_python(code: str) -> bool:
    """Reject imports, dunder reach-through, and calls that escape a sandbox."""
    if not isinstance(code, str) or not code.strip() or len(code) > 20_000:
        return False
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    blocked_calls = {"exec", "eval", "open", "compile", "__import__", "input", "breakpoint"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            return False
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("__"):
            return False
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in blocked_calls
        ):
            return False
    return True


def _digest(value) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def propose(service, params):
    description = str(params.get("description") or "").strip()
    if not description or len(description) > 4000:
        raise ValueError("Describe the repository workflow in up to 4,000 characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in description):
        raise ValueError("The workflow description contains unsupported control characters")
    slug = name(params.get("name") or slugify(description))
    bundle = _bundle(description, slug)
    route = (
        params.get("route") if isinstance(params.get("route"), dict) else {"source": "definition"}
    )
    review = inspect_definition(
        service,
        {"project": params["project"], "name": slug, "yaml": bundle["yaml"], "route": route},
    )
    return {
        "name": slug,
        "description": description,
        "yaml": review["yaml"],
        "review": review["review"],
        "digest": review["digest"],
        "expected_file_digest": review["expected_file_digest"],
        "warnings": review["warnings"],
        "skill": bundle["skill"],
        "program": bundle["program"],
        "skill_digest": _digest(bundle["skill"]),
        "program_digest": _digest(bundle["program"]),
        "recursion": bundle["recursion"],
        "recursion_digest": _digest(bundle["recursion"]),
        "plugin": bundle["plugin"],
        "plugin_digest": _digest(bundle["plugin"]),
        "panels": bundle["panels"],
        "layout_digest": bundle["layout_digest"],
        "route": review["route"],
        "enabled": False,
        "installed": False,
    }


def _write(root, relative, text):
    path = within(root, relative)
    from .studio import _atomic

    _atomic(path, text)
    return path


def commit(service, params):
    """Save the reviewed draft. Enabling the revision is a separate action."""
    panels = params.get("panels")
    if not isinstance(panels, list) or not panels or any(panel not in PANELS for panel in panels):
        raise ValueError("Choose the review panels from the existing workspace")
    if panels[0] != "Workspace" or "Tools" not in panels:
        raise ValueError("Keep Agent Space and Tools available in the repository layout")
    layout = {"name": name(params.get("name") or ""), "panels": list(panels)}
    skill, program = str(params.get("skill") or ""), str(params.get("program") or "")
    recursion, plugin = str(params.get("recursion") or ""), str(params.get("plugin") or "")
    if (
        params.get("layout_digest") != _digest(layout)
        or params.get("skill_digest") != _digest(skill)
        or params.get("program_digest") != _digest(program)
        or params.get("recursion_digest") != _digest(recursion)
        or params.get("plugin_digest") != _digest(plugin)
        or len(skill) > 20_000
        or len(program) > 20_000
        or len(recursion) > 20_000
        or len(plugin) > 20_000
    ):
        raise ValueError("The draft changed. Review it again before saving")
    if not pure_python(plugin):
        raise ValueError("This check can only use pure Python inside Monty")
    reason = str(params.get("reason") or "").strip()
    if not reason or len(reason) > 2000:
        raise ValueError("Describe this revision in up to 2,000 characters")
    if reviewed(service, params)["name"] != layout["name"]:
        raise ValueError("The saved harness name did not match this draft")
    saved = save(
        service,
        {
            "project": params["project"],
            "review": params.get("review"),
            "digest": params.get("digest"),
            "reason": reason,
            "expected_file_digest": params.get("expected_file_digest", ""),
        },
    )
    if saved["id"] != layout["name"]:
        raise ValueError("The saved harness name did not match this draft")
    root = service.project(params["project"])
    folder = f".superqode/creator/{layout['name']}"
    _write(root, f"{folder}/SKILL.md", skill)
    _write(root, f"{folder}/work-program.md", program)
    _write(root, f"{folder}/recursion.md", recursion)
    _write(root, f"{folder}/plugin.py", plugin)
    _write(root, f"{folder}/panels.json", json.dumps(layout, indent=2) + "\n")
    return {
        **saved,
        "panels": layout["panels"],
        "enabled": False,
        "installed": False,
        "folder": folder,
    }


def run_check(service, params):
    """Run the saved pure-Python check in Monty. Never install it or use the host."""
    slug = name(params.get("name") or "")
    root = service.project(params["project"])
    path = within(root, f".superqode/creator/{slug}/plugin.py")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000:
        raise ValueError("Save the Super Agent draft before running its Monty check")
    code = path.read_text(encoding="utf-8")
    if params.get("plugin_digest") != _digest(code):
        raise ValueError("The Monty check changed. Review it again before running")
    if not pure_python(code):
        raise ValueError("This check can only use pure Python inside Monty")
    from superqode.tools.monty_tool import _load_monty, run_monty_snippet

    module = _load_monty()
    if module is None:
        raise ValueError("Monty is not installed. The check was not run on the host.")
    output = run_monty_snippet(module, code)
    return {
        "output": output,
        "sandbox": "monty",
        "installed": False,
        "filesystem": False,
        "network": False,
    }


def layout(service, params):
    root = service.project(params["project"])
    directory = within(root, ".superqode/creator")
    if not directory.is_dir():
        return {"name": "", "panels": []}
    rows = []
    for folder in directory.iterdir():
        panel = folder / "panels.json"
        if (
            folder.is_symlink()
            or not folder.is_dir()
            or panel.is_symlink()
            or not panel.is_file()
            or panel.stat().st_size > 20_000
        ):
            continue
        try:
            data = json.loads(panel.read_text())
        except (OSError, ValueError):
            continue
        if (
            isinstance(data, dict)
            and data.get("name") == folder.name
            and isinstance(data.get("panels"), list)
            and all(item in PANELS for item in data["panels"])
        ):
            rows.append((panel.stat().st_mtime, data))
    if not rows:
        return {"name": "", "panels": []}
    newest = max(rows, key=lambda item: item[0])[1]
    return {"name": newest["name"], "panels": newest["panels"]}
