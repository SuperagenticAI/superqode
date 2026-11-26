# Pydantic Coder Commands

`superqode pydantic-coder` manages the experimental Pydantic Coder ACP connector,
using the coding engine behind Pax. Its terminal UI and plugins are separate.
The pinned runtime installs in its own environment alongside the engine.

## Setup and diagnostics

```bash
sq pydantic-coder setup
sq pydantic-coder doctor
```

Both commands accept `--python PATH` to select the Python executable in a separate
virtual environment. `setup` explicitly installs the pinned SDKs; `doctor` checks
that environment without downloading packages or making model calls.

## Chat and resume

```bash
sq pydantic-coder chat --project-dir ./my-project
sq pydantic-coder chat --project-dir ./my-project --model PROVIDER:MODEL
sq pydantic-coder chat --project-dir ./my-project --resume SESSION_ID
```

Configure your provider credentials through SuperQode or the environment first.
In the session, `/models` lists choices, `/model PROVIDER:MODEL` selects one and
`/quit` exits. Provider billing applies when you send prompts. Writes, commands
and MCP tool calls require explicit approval. Approved commands run as your user.

## ACP server

`sq pydantic-coder serve [--model PROVIDER:MODEL]` serves ACP over standard input
and output for an ACP client. The installed `superqode-pydantic-coder` launcher
provides the same server entry point. It requires the optional runtime.

## Terminal UI and macOS

Use `:connect acp pydantic-coder`, or `:pydantic-coder chat` with no options, to
connect through the TUI. `:pydantic-coder setup` and `:pydantic-coder doctor` use
the CLI setup and diagnostic commands. Run advanced chat options and the stdio
server in a separate terminal. In macOS, choose the experimental agent under
**ACP agents**, install its runtime, check the connection and select a model in
Agent controls. See the [ACP catalog guide](../providers/acp.md) for details.
