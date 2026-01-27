<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# OpenResponses Gateway

OpenResponses is a unified API specification that provides a consistent interface across multiple AI providers, with advanced features like streaming, reasoning, and built-in tools.

---

## Overview

OpenResponses provides:

- **Unified API**: Single interface for multiple AI providers
- **Streaming**: 45+ event types for real-time updates
- **Reasoning**: Access to model thinking/reasoning content
- **Built-in Tools**: Native support for `apply_patch`, `code_interpreter`, `file_search`
- **Message Conversion**: Automatic conversion between messages and items

---

## What is OpenResponses?

OpenResponses is an open specification for AI provider APIs that extends beyond basic chat completions. It supports:

- **Structured Outputs**: Items-based message format
- **Reasoning Content**: Access to model reasoning/thinking
- **Rich Streaming**: Detailed streaming events for progress tracking
- **Native Tools**: Built-in tool definitions and execution
- **Provider Agnostic**: Works with any OpenResponses-compatible provider

---

## Supported Providers

OpenResponses works with providers that implement the specification:

- **Ollama**: With OpenResponses support enabled
- **vLLM**: Via OpenResponses adapter
- **Custom Servers**: Any OpenResponses-compatible endpoint
- **Cloud Providers**: With OpenResponses-compatible APIs

---

## Features

### Streaming with 45+ Event Types

OpenResponses supports rich streaming with detailed events:

- `response.created`: Response started
- `response.in_progress`: Response in progress
- `response.output.text.delta`: Text token delta
- `response.reasoning.delta`: Reasoning content delta
- `response.function_call.arguments.delta`: Tool call arguments
- `response.completed`: Response finished

```python
async for chunk in gateway.stream_completion(messages, model):
    if chunk.type == "response.output.text.delta":
        print(chunk.content, end="")
    elif chunk.type == "response.reasoning.delta":
        print(f"[Reasoning: {chunk.content}]", end="")
```

### Reasoning/Thinking Content

Access model reasoning alongside output:

```python
response = await gateway.chat_completion(messages, model)
print(f"Output: {response.content}")
print(f"Reasoning: {response.reasoning}")  # Model's thinking process
```

**Reasoning Levels:**

- `low`: Minimal reasoning (faster, less insight)
- `medium`: Balanced reasoning (default)
- `high`: Detailed reasoning (slower, more insight)

### Built-in Tools

OpenResponses defines native tools:

#### `apply_patch`

Apply code patches directly:

```json
{
  "type": "apply_patch",
  "patch": {
    "path": "src/api/users.py",
    "diff": "@@ -42,7 +42,9 @@\n-sql = f\"...\"\n+sql = \"...\"\n+params = (...)"
  }
}
```

#### `code_interpreter`

Execute code in isolated environment:

```json
{
  "type": "code_interpreter",
  "code": "def test_api():\n    response = requests.get('...')\n    assert response.status_code == 200"
}
```

#### `file_search`

Search and retrieve files:

```json
{
  "type": "file_search",
  "query": "authentication middleware",
  "paths": ["src/"]
}
```

---

## Usage

### Basic Usage

```python
from superqode.providers.gateway import OpenResponsesGateway

gateway = OpenResponsesGateway(
    base_url="http://localhost:11434",
    reasoning_effort="medium"
)

# Chat completion
response = await gateway.chat_completion(
    messages=[
        {"role": "user", "content": "Analyze this code..."}
    ],
    model="qwen3:8b"
)

print(response.content)
```

### Streaming

```python
async for chunk in gateway.stream_completion(
    messages=messages,
    model="qwen3:8b"
):
    if chunk.type == "response.output.text.delta":
        print(chunk.content, end="", flush=True)
```

### With Tools

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                }
            }
        }
    }
]

response = await gateway.chat_completion(
    messages=messages,
    model="qwen3:8b",
    tools=tools
)
```

### Reasoning Configuration

```python
gateway = OpenResponsesGateway(
    base_url="http://localhost:11434",
    reasoning_effort="high",  # Get detailed reasoning
    truncation="auto"         # Auto-truncate if needed
)
```

---

## Configuration

### SuperQode Configuration

```yaml
# superqode.yaml
providers:
  openresponses:
    base_url: http://localhost:11434
    reasoning_effort: medium
    truncation: auto
    timeout: 300
```

### Environment Variables

```bash
export OPENRESPONSES_BASE_URL=http://localhost:11434
export OPENRESPONSES_REASONING_EFFORT=medium
export OPENRESPONSES_TRUNCATION=auto
```

### Gateway Initialization

```python
from superqode.providers.gateway import OpenResponsesGateway

gateway = OpenResponsesGateway(
    base_url="http://localhost:11434",
    api_key=None,  # Optional for local providers
    reasoning_effort="medium",
    truncation="auto",
    timeout=300.0,
    track_costs=False  # Local providers typically don't charge
)
```

---

## Message ↔ Item Conversion

OpenResponses uses an items-based format internally. SuperQode automatically converts:

### Messages to Items

```python
from superqode.providers.openresponses import messages_to_items

messages = [
    {"role": "user", "content": "Hello"}
]

items = messages_to_items(messages)
# Converts to OpenResponses item format
```

### Items to Messages

```python
from superqode.providers.openresponses import items_to_messages

# After receiving OpenResponses response
messages = items_to_messages(response.items)
```

---

## Streaming Events

### Event Types

| Event | Description |
|-------|-------------|
| `response.created` | Response started |
| `response.in_progress` | Processing in progress |
| `response.output.text.delta` | Text token delta |
| `response.output.text.done` | Text output complete |
| `response.reasoning.delta` | Reasoning content delta |
| `response.reasoning.done` | Reasoning complete |
| `response.function_call.arguments.delta` | Tool arguments delta |
| `response.function_call.arguments.done` | Tool arguments complete |
| `response.completed` | Response finished |

### Processing Events

```python
async for chunk in gateway.stream_completion(messages, model):
    event_type = chunk.type

    if event_type == "response.output.text.delta":
        # Accumulate text
        output_text += chunk.content

    elif event_type == "response.reasoning.delta":
        # Accumulate reasoning
        reasoning += chunk.content

    elif event_type == "response.function_call.arguments.delta":
        # Accumulate tool call
        tool_args += chunk.content

    elif event_type == "response.completed":
        # Process final response
        final_response = chunk.response
```

---

## Tool Conversion

OpenResponses tools are automatically converted:

```python
from superqode.providers.openresponses import (
    convert_tools_to_openresponses,
    convert_tools_from_openresponses
)

# Convert SuperQode tools to OpenResponses
openresponses_tools = convert_tools_to_openresponses(tools)

# Convert OpenResponses tools back
superqode_tools = convert_tools_from_openresponses(openresponses_tools)
```

---

## Reasoning Levels

### Low

Minimal reasoning, fastest:

```python
gateway = OpenResponsesGateway(
    reasoning_effort="low"
)
```

**Use when:**
- Speed is critical
- Simple tasks
- Reasoning not needed

### Medium (Default)

Balanced reasoning:

```python
gateway = OpenResponsesGateway(
    reasoning_effort="medium"
)
```

**Use when:**
- General QE tasks
- Need some insight
- Balance of speed and detail

### High

Detailed reasoning, slower:

```python
gateway = OpenResponsesGateway(
    reasoning_effort="high"
)
```

**Use when:**
- Complex analysis needed
- Understanding model logic
- Debugging model behavior

---

## Truncation

### Auto (Default)

Automatically truncate if needed:

```python
gateway = OpenResponsesGateway(
    truncation="auto"
)
```

### Disabled

Never truncate:

```python
gateway = OpenResponsesGateway(
    truncation="disabled"
)
```

---

## Error Handling

```python
from superqode.providers.gateway import (
    GatewayError,
    ModelNotFoundError,
    RateLimitError
)

try:
    response = await gateway.chat_completion(messages, model)
except ModelNotFoundError:
    print(f"Model {model} not found")
except RateLimitError:
    print("Rate limit exceeded")
except GatewayError as e:
    print(f"Gateway error: {e}")
```

---

## Best Practices

### 1. Use Appropriate Reasoning Level

```python
# Quick tasks
gateway = OpenResponsesGateway(reasoning_effort="low")

# QE analysis
gateway = OpenResponsesGateway(reasoning_effort="medium")

# Deep investigation
gateway = OpenResponsesGateway(reasoning_effort="high")
```

### 2. Handle Streaming Efficiently

```python
async def process_stream(gateway, messages, model):
    output = ""
    reasoning = ""

    async for chunk in gateway.stream_completion(messages, model):
        if chunk.type == "response.output.text.delta":
            output += chunk.content
            # Process incrementally
            process_text_delta(chunk.content)
        elif chunk.type == "response.reasoning.delta":
            reasoning += chunk.content

    return output, reasoning
```

### 3. Use Tools for Complex Tasks

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "analyze_code",
            "description": "Analyze code quality",
            "parameters": {...}
        }
    }
]

response = await gateway.chat_completion(
    messages,
    model,
    tools=tools
)
```

---

## Troubleshooting

### Provider Not Compatible

**Problem**: Provider doesn't support OpenResponses

**Solution**: Use standard gateway instead:

```python
from superqode.providers.gateway import LiteLLMGateway

gateway = LiteLLMGateway()  # Standard gateway
```

### Reasoning Not Available

**Problem**: Provider doesn't support reasoning

**Solution**: Reasoning will be empty; output still works:

```python
response = await gateway.chat_completion(messages, model)
if response.reasoning:
    print(f"Reasoning: {response.reasoning}")
else:
    print("Reasoning not available for this provider")
```

### Streaming Errors

**Problem**: Streaming events not parsed correctly

**Solution**: Check event parser:

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Integration Examples

### With Ollama

```python
gateway = OpenResponsesGateway(
    base_url="http://localhost:11434"
)

response = await gateway.chat_completion(
    messages=[{"role": "user", "content": "Test"}],
    model="qwen3:8b"
)
```

### With vLLM

```python
gateway = OpenResponsesGateway(
    base_url="http://localhost:8000"
)

response = await gateway.chat_completion(
    messages=[{"role": "user", "content": "Test"}],
    model="Qwen/Qwen2.5-Coder-7B-Instruct"
)
```

---

## Next Steps

- [Local Providers](local.md) - Local model setup
- [BYOK Providers](byok.md) - Cloud provider setup
- [Provider Commands](../cli-reference/provider-commands.md) - CLI reference
