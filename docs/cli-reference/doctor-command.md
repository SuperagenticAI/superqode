# Doctor Command

`superqode doctor` checks local developer setup without generating model text
or running coding tools. Use `superqode doctor --json` for structured output.

```bash
superqode doctor
superqode doctor --json
```

The report includes the source version, Python support, installed core
packages, configuration validity, Git/uv/tmux availability, terminal metadata,
recent project sessions, provider configuration, and the resolved default
model. Local discovery lists installed or loaded models; a stopped local
server is not reported as a usable default. Stored API credentials and
environment credentials use the same lookup as model requests.

Global `--provider`, `--model` and model-aware harness choices are reflected
in the selected route. `selected_route_configured` reports that route's setup
status. A missing credential or unavailable local model produces setup guidance
instead of recommending a task against that unconfigured route.

`ready` means a model route is configured and basic local requirements pass.
`inference_verified` remains false: a configured credential can still be
expired, out of quota, or unable to access a particular model. Terminal
capabilities are reported as observed metadata, not active escape-sequence
or clipboard probes. SSH and tmux notes help diagnose color, clipboard and
shortcut differences without reading clipboard contents.

For deeper connection checks, use `:doctor connection` in the TUI,
`superqode agents doctor`, or `superqode runtime doctor`. These checks are
separate from inference and tool execution. The report gives an explicit
provider/model command when a configured default exists; otherwise it gives
setup guidance.
