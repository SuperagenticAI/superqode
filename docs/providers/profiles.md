# Model Profiles

Model profiles are SuperQode's way to apply **per-provider** or **per-model**
tuning to the agent loop without forking the harness. They are tiny
declarative bundles that say:

> "Whenever the agent runs against this provider (or this exact model), do
> these things."

You can:

- Append a **system-prompt suffix** that lands closest to the conversation.
- Hide specific **tools** from the model.
- Inject **gateway kwargs** (e.g. headers, response-API toggles): statically
  or computed at request time.
- Run a one-shot **pre-init hook** (e.g. version-pin enforcement,
  environment validation) before the first request.

The pattern is borrowed from
[langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) but
collapsed into a single struct: SuperQode does not split
model-construction from runtime behaviour the way LangChain does.

## Profile selection

| You want to... | Use a profile |
|---|---|
| Add Anthropic's "investigate before answering" guidance only for Claude models | ✓ |
| Inject OpenRouter app-attribution headers when an env var is unset | ✓ |
| Force a smaller model to skip a tool it handles poorly | ✓ |
| Enforce a minimum SDK version for a particular provider | ✓ |
| Apply a system prompt to **every** request regardless of model | use `AgentConfig.custom_system_prompt` instead |
| Change tool **execution** logic | the tool registry / permission manager |

## The `ModelProfile` struct

```python
from superqode.providers.profiles import ModelProfile

ModelProfile(
    system_prompt_suffix: Optional[str] = None,
    excluded_tools: frozenset[str] = frozenset(),
    init_kwargs: Mapping[str, Any] = {},
    init_kwargs_factory: Optional[Callable[[], dict]] = None,
    pre_init: Optional[Callable[[str], None]] = None,
)
```

All fields are optional: an empty `ModelProfile()` is a valid no-op.

The struct is frozen: trying to mutate `profile.init_kwargs["x"] = 1` raises
`TypeError`. Re-register the key to layer new fields on top instead.

## Registering a profile

```python
from superqode.providers.profiles import ModelProfile, register_model_profile

register_model_profile(
    "anthropic:<anthropic-balanced-model>",
    ModelProfile(system_prompt_suffix="Think step by step."),
)
```

Keys are either a **bare provider** (`"anthropic"`, applies to every model
from that provider) or a full **`provider:model`** spec (`"anthropic:<anthropic-balanced-model>"`,
applies only to that one model).

Registrations are **additive**: if a profile already exists under the same
key (including a built-in), the new profile is layered on top with the
incoming fields winning on conflicts. To completely replace, call
`clear_registry()` (test helper) first.

## Lookup and merge semantics

On every agent request, the loop resolves a profile via:

```python
resolve_model_profile(provider, model)
```

Resolution order:

1. Exact `provider:model` match.
2. Bare `provider` match.
3. Empty default profile.

When **both** a provider-level and a model-level profile are registered, they
are merged with model-level fields winning. The merge rules:

| Field | Merge rule |
|---|---|
| `system_prompt_suffix` | model wins if set; else provider |
| `excluded_tools` | union of both sets |
| `init_kwargs` | dict merge, model wins per key |
| `init_kwargs_factory` | chained: provider runs, then model; model keys win on collision |
| `pre_init` | chained: provider runs first, then model |

## How profiles plug into the agent loop

Profiles are not called directly. The loop applies them at three points:

1. **System-prompt assembly**: `system_prompt_suffix` is appended to the
   final prompt with a blank-line separator.
2. **Tool-definition build**: names in `excluded_tools` are filtered out
   before tool defs are sent to the model.
3. **Gateway request**: `init_kwargs` + `init_kwargs_factory()` are merged
   into the `chat_completion` / `stream_completion` kwargs. The explicit
   arguments the loop already passes (`temperature`, `max_tokens`, `tools`,
   etc.) still take precedence.

The `pre_init` hook runs exactly once per `(provider, model)` pair, the
first time the loop sees that spec. Subsequent requests skip the hook.

## Built-in profiles

These ship with SuperQode and load lazily on first registry access. You can
layer your own profile on top of any of them with another
`register_model_profile()` call.

### Anthropic: Claude family

Registered under:

- `anthropic:<anthropic-balanced-model>`
- `anthropic:claude-opus-4-7`
- `anthropic:<anthropic-model>`
- `anthropic:<anthropic-fast-model>`

Applies a `system_prompt_suffix` with three blocks drawn from Anthropic's
[prompt-engineering best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices):

- `<use_parallel_tool_calls>`: encourages parallel tool calls when there
  are no dependencies between them.
- `<investigate_before_answering>`: discourages speculation about files
  the model has not read.
- `<tool_result_reflection>`: encourages reflection between tool calls.

### OpenRouter

Registered under: `openrouter`

Uses `init_kwargs_factory` to inject `app_url` and `app_title` headers when
the corresponding env vars are unset. Set `OPENROUTER_APP_URL` or
`OPENROUTER_APP_TITLE` to override: an explicitly empty string is treated
as "user-set, do not override".

## Examples

### Add a custom suffix on top of the built-in Anthropic one

The registration is additive: the merged suffix is provider's suffix +
yours, separated by a blank line.

```python
register_model_profile(
    "anthropic:<anthropic-balanced-model>",
    ModelProfile(system_prompt_suffix="Respond in under 100 words."),
)
```

### Hide `bash` from a smaller model

```python
register_model_profile(
    "openrouter:meta-llama/llama-3.2-3b-instruct",
    ModelProfile(excluded_tools=frozenset({"bash"})),
)
```

### Provider-wide env-aware headers

```python
register_model_profile(
    "my_provider",
    ModelProfile(
        init_kwargs_factory=lambda: {
            "extra_headers": {"X-Trace-Id": os.environ.get("TRACE_ID", "")},
        },
    ),
)
```

### Pre-init version pin

```python
from importlib.metadata import version
from packaging.version import Version

def _require_min_sdk(spec: str) -> None:
    if Version(version("my-sdk")) < Version("2.0"):
        raise ImportError("my-sdk>=2.0 required for spec " + spec)

register_model_profile(
    "my_provider",
    ModelProfile(pre_init=_require_min_sdk),
)
```

## Test helpers

```python
from superqode.providers.profiles import clear_registry

# In a pytest fixture:
@pytest.fixture(autouse=True)
def _reset_profiles():
    clear_registry()
    yield
    clear_registry()
```

`clear_registry()` drops every registration and resets the
builtins-loaded flag. The next `resolve_model_profile` call reloads the
built-ins lazily.

## Reading list

- The implementation: [`src/superqode/providers/profiles.py`](https://github.com/Shashikant86/superqode/blob/main/src/superqode/providers/profiles.py)
- Built-in profiles: [`src/superqode/providers/_builtin_profiles.py`](https://github.com/Shashikant86/superqode/blob/main/src/superqode/providers/_builtin_profiles.py)
