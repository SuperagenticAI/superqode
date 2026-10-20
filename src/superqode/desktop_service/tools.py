"""Typed native forms for advanced engine workflows, with private argument transport."""

from __future__ import annotations

import json
import re
from pathlib import Path

import click

GROUPS = {
    "work",
    "memory",
    "skills",
    "mcp",
    "harness",
    "skillopt",
    "optimize",
    "local",
    "models",
    "runtime",
    "providers",
    "policy",
    "profiles",
    "sandbox",
    "trust",
    "sessions",
    "benchmark",
    "gauge",
    "doctor",
    "agents",
    "factory",
    "plugins",
    "tools",
    "a2a-keys",
}
EXCLUDED = {"serve", "server", "daemon", "tui", "install", "uninstall"}


def scalar(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [scalar(v) for v in value]
    return str(value) if isinstance(value, Path) else None


def command_catalog():
    from superqode.main import cli_main

    root = click.Context(cli_main)
    result = []

    def visit(command, path, ancestors):
        fields = list(ancestors)
        for parameter in command.params:
            if parameter.name in {"help", "version"} or getattr(parameter, "hidden", False):
                continue
            secret = (
                bool(
                    getattr(parameter, "hide_input", False)
                    or re.search(
                        r"(^|_)(api_key|access_token|refresh_token|bearer_token|auth_token|password|secret|client_secret|credential|token)$",
                        parameter.name or "",
                    )
                )
                and not (parameter.name or "").endswith("_env")
                and not isinstance(parameter.type, click.Path)
            )
            default = scalar(parameter.default) if not callable(parameter.default) else None
            fields.append(
                {
                    "id": " ".join(path) + ":" + parameter.name,
                    "name": parameter.name,
                    "label": parameter.name.replace("_", " ").capitalize(),
                    "help": getattr(parameter, "help", "") or "",
                    "required": parameter.required,
                    "secret": secret,
                    "default": None if secret else default,
                    "choices": list(parameter.type.choices)
                    if isinstance(parameter.type, click.Choice)
                    else [],
                    "boolean": bool(getattr(parameter, "is_bool_flag", False)),
                    "multiple": bool(getattr(parameter, "multiple", False) or parameter.nargs != 1),
                    "path": isinstance(parameter.type, click.Path),
                    "file": getattr(parameter.type, "file_okay", False),
                    "directory": getattr(parameter.type, "dir_okay", False),
                }
            )
        if not isinstance(command, click.Group) or command.invoke_without_command:
            result.append(
                {
                    "id": " ".join(path),
                    "name": " ".join(path[1:]).replace("-", " ").capitalize()
                    or path[0].capitalize(),
                    "category": path[0],
                    "description": command.help or command.short_help or "",
                    "fields": fields,
                }
            )
        if isinstance(command, click.Group):
            context = click.Context(command)
            for name in command.list_commands(context):
                if name in EXCLUDED:
                    continue
                child = command.get_command(context, name)
                if child and not child.hidden:
                    visit(child, path + [name], fields)

    for name in sorted(GROUPS):
        command = cli_main.get_command(root, name)
        if command:
            visit(command, [name], [])
    return result


def tool_arguments(identity: str, values: dict):
    from superqode.main import cli_main

    rows = {row["id"]: row for row in command_catalog()}
    if identity not in rows:
        raise ValueError("Choose an available native workflow")
    row = rows[identity]
    field_ids = {field["id"] for field in row["fields"]}
    if set(values) - field_ids:
        raise ValueError("Unexpected workflow parameters")
    argv, secrets = [], []
    command = cli_main
    for index, name in enumerate(identity.split(" ")):
        command = command.get_command(click.Context(command), name)
        argv.append(name)
        path = " ".join(identity.split(" ")[: index + 1])
        for parameter in command.params:
            key = path + ":" + parameter.name
            if key not in field_ids:
                continue
            value = values.get(key)
            if value is None or value == "":
                if parameter.required:
                    raise ValueError("Enter " + parameter.name.replace("_", " "))
                continue
            if isinstance(parameter, click.Option) and parameter.is_bool_flag:
                desired = value is True
                if desired != bool(parameter.default):
                    option = (
                        parameter.opts[0]
                        if desired == bool(parameter.flag_value)
                        else (parameter.secondary_opts or [None])[0]
                    )
                    if not option:
                        raise ValueError("This flag cannot express the selected value")
                    argv.append(option)
                continue
            items = value if isinstance(value, list) else [str(value)]
            if parameter.nargs > 1 and len(items) != parameter.nargs:
                raise ValueError(f"{parameter.name} needs {parameter.nargs} values")
            for item in items:
                # Ask Click's existing type validator; preserve the original literal argv.
                if parameter.nargs == 1:
                    parameter.type.convert(item, parameter, click.Context(command))
                if isinstance(parameter, click.Option) and parameter.nargs == 1:
                    argv.append(parameter.opts[0])
                elif isinstance(parameter, click.Option) and item == items[0]:
                    argv.append(parameter.opts[0])
                argv.append(str(item))
            if any(field["id"] == key and field["secret"] for field in row["fields"]):
                secrets.extend(str(item) for item in items if item)
    if len(json.dumps(argv).encode()) > 60_000:
        raise ValueError("Workflow arguments exceed 60 KB; use a task or input file")
    return {
        "argv": argv,
        "secrets": secrets,
        "title": identity.split(" ")[0].capitalize() + " · " + row["name"],
        "recorded_values": {
            key: "[REDACTED]"
            if any(f["id"] == key and f["secret"] for f in row["fields"])
            else value
            for key, value in values.items()
        },
    }


def run_tool(request, emit):
    import os
    import subprocess
    import sys

    argv = json.loads(os.environ.pop("SUPERQODE_DESKTOP_TOOL_ARGV"))
    driver = "import json,sys; from superqode.main import cli_main; cli_main(args=json.loads(sys.stdin.readline()),prog_name='superqode')"
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", driver],
        cwd=request["cwd"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process.stdin.write(json.dumps(argv) + "\n")
    process.stdin.close()
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    for line in process.stdout:
        emit("output", {"text": ansi.sub("", line)[:8000]})
    code = process.wait()
    emit("result", {"status": "completed" if code == 0 else "failed", "exit_code": code})
