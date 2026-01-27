# Local Providers

Run AI models locally for privacy, cost savings, and offline use.

---

## Overview

Local providers offer:

- **Privacy**: Data stays on your machine
- **Cost savings**: No API fees
- **Offline use**: Work without internet
- **Full control**: Model selection and tuning

---

## Supported Providers

| Provider | Best For | Setup Complexity |
|----------|----------|------------------|
| **Ollama** | Easy setup, many models | Easy |
| **LM Studio** | GUI interface, beginners | Easy |
| **MLX** | Apple Silicon, performance | Medium |
| **vLLM** | Production, high throughput | Advanced |

---

## Ollama

The easiest way to run local models.

### Installation

**macOS**:
```bash
brew install ollama
```

**Linux**:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows**: Download from [ollama.com](https://ollama.com)

### Quick Start

```bash
# Start Ollama
ollama serve

# Pull a model
ollama pull qwen3:8b

# Connect in SuperQode
superqode connect local ollama qwen3:8b
```

### Recommended Models

| Model | Size | Best For |
|-------|------|----------|
| `qwen3:8b` | ~5GB | General use, coding |
| `llama3.2:latest` | ~4GB | General use |
| `codellama:13b` | ~7GB | Code analysis |
| `deepseek-coder:6.7b` | ~4GB | Code tasks |

### Configuration

```yaml
providers:
  ollama:
    base_url: http://localhost:11434
    type: openai-compatible
    recommended_models:
      - qwen3:8b
      - llama3.2:latest
      - codellama:13b
```

---

## LM Studio

GUI-based local model runner.

### Installation

1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Install and open LM Studio
3. Download a model (search for "qwen" or "llama")
4. Load the model
5. Start Local Server (port 1234)

### Connect

```bash
superqode connect local lmstudio local-model
```

### Configuration

```yaml
providers:
  lmstudio:
    base_url: http://localhost:1234
    type: openai-compatible
```

### Tips

- Keep LM Studio running in background
- Load model before connecting
- Check "Local Server" tab for status

---

## MLX (Apple Silicon)

Optimized for M1/M2/M3 Macs.

### Installation

```bash
pip install mlx-lm
```

### Quick Start

```bash
# Download model
mlx_lm.download mlx-community/Qwen2.5-Coder-3B-4bit

# Start server (in separate terminal)
mlx_lm.server --model mlx-community/Qwen2.5-Coder-3B-4bit

# Connect in SuperQode
superqode connect local mlx mlx-community/Qwen2.5-Coder-3B-4bit
```

### Recommended Models

| Model | RAM | Quality |
|-------|-----|---------|
| `mlx-community/Qwen2.5-Coder-0.5B-Instruct-4bit` | 2GB | Basic |
| `mlx-community/Qwen2.5-Coder-3B-4bit` | 4GB | Good |
| `mlx-community/Qwen2.5-Coder-7B-4bit` | 8GB | Better |
| `mlx-community/Qwen3-30B-A3B-4bit` | 16GB | Best |

### MLX Commands

```bash
# List available models
superqode providers mlx list

# Show suggested models
superqode providers mlx models

# Check installation
superqode providers mlx check

# Full setup guide
superqode providers mlx setup
```

### Configuration

```yaml
providers:
  mlx:
    base_url: http://localhost:8080
    type: openai-compatible
```

### Limitations

- One server per model
- Single request at a time
- MoE models not supported

---

## vLLM

High-performance inference for production.

### Installation

```bash
pip install vllm
```

### Quick Start

```bash
# Start server
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --port 8000

# Connect in SuperQode
superqode connect local vllm Qwen/Qwen2.5-Coder-7B-Instruct
```

### Configuration

```yaml
providers:
  vllm:
    base_url: http://localhost:8000
    type: openai-compatible
```

### Benefits

- High throughput
- Continuous batching
- PagedAttention

---

## SGLang

Fast structured generation framework optimized for complex prompts.

### Installation

```bash
pip install "sglang[all]"
```

### Quick Start

```bash
# Start server
python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-7B-Instruct \
  --port 30000

# Connect in SuperQode
superqode connect local sglang Qwen/Qwen2.5-Coder-7B-Instruct
```

### Configuration

```yaml
providers:
  sglang:
    base_url: http://localhost:30000/v1
    type: openai-compatible
```

### Features

- **RadixAttention**: Fast KV cache reuse for better performance
- **Compressed FSM**: Efficient structured output generation
- **OpenAI-compatible API**: Drop-in replacement for OpenAI endpoints

### Benefits

- Faster inference for complex prompts
- Efficient structured generation
- Good for code analysis tasks

### Recommended Models

| Model | Size | Best For |
|-------|------|----------|
| `Qwen/Qwen2.5-Coder-7B-Instruct` | ~14GB | Code tasks |
| `meta-llama/Llama-3.3-70B-Instruct` | ~140GB | Large codebases |

---

## TGI (Text Generation Inference)

HuggingFace's production-grade inference server with multi-GPU support.

### Installation

```bash
# Using Docker (recommended)
docker run --gpus all \
  -p 8080:80 \
  -v $PWD/data:/data \
  ghcr.io/huggingface/text-generation-inference:latest \
  --model-id Qwen/Qwen2.5-Coder-7B-Instruct

# Or using Python
pip install text-generation
```

### Quick Start

```bash
# Using Docker
docker run -d --gpus all \
  -p 8080:80 \
  -v $PWD/data:/data \
  ghcr.io/huggingface/text-generation-inference:latest \
  --model-id Qwen/Qwen2.5-Coder-7B-Instruct \
  --port 80

# Connect in SuperQode
superqode connect local tgi Qwen/Qwen2.5-Coder-7B-Instruct
```

### Configuration

```yaml
providers:
  tgi:
    base_url: http://localhost:8080
    type: huggingface
```

### Features

- **Flash Attention & Paged Attention**: Memory-efficient attention
- **Continuous Batching**: Efficient request handling
- **Tensor Parallelism**: Multi-GPU support
- **Token Streaming**: Real-time token output
- **Tool/Function Calling**: Built-in tool support

### Benefits

- Production-ready server
- Multi-GPU scaling
- Memory efficient
- Good for high-load scenarios

### Multi-GPU Setup

```bash
docker run --gpus all \
  -p 8080:80 \
  ghcr.io/huggingface/text-generation-inference:latest \
  --model-id Qwen/Qwen2.5-Coder-7B-Instruct \
  --num-shard 4  # Use 4 GPUs
```

---

## llama.cpp

CPU/GPU inference server for GGUF format models.

### Installation

```bash
# Clone and build
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
make

# Or use pre-built server
# Download from releases
```

### Quick Start

```bash
# Start server
./llama-server \
  -m models/qwen2.5-coder-7b.Q8_0.gguf \
  --port 8080 \
  --host 0.0.0.0

# Connect in SuperQode
superqode connect local llamacpp local-model
```

### Configuration

```yaml
providers:
  llamacpp:
    base_url: http://localhost:8080/v1
    type: openai-compatible
```

### Features

- **GGUF Format**: Efficient model format
- **CPU/GPU Support**: Works on both CPU and GPU
- **Low Memory**: Efficient memory usage
- **OpenAI-compatible**: Standard API interface

### Benefits

- Runs on CPU efficiently
- Works with quantized models
- Low resource requirements
- Good for older hardware

### Model Format

llama.cpp uses GGUF format models:

```bash
# Convert model to GGUF
python convert.py --outfile model.gguf --outtype f16 model/

# Quantize model
./quantize model.gguf model-q8_0.gguf Q8_0
```

### Quantization Levels

| Level | Size | Quality | Speed |
|-------|------|---------|-------|
| `F16` | 100% | Best | Medium |
| `Q8_0` | 50% | Very Good | Fast |
| `Q4_K_M` | 25% | Good | Very Fast |
| `Q2_K` | 12.5% | Basic | Fastest |

---

## Per-Role Configuration

Use local models for specific roles:

```yaml
team:
  modes:
    qe:
      roles:
        # Cloud for critical analysis
        security_tester:
          mode: byok
          provider: anthropic
          model: claude-sonnet-4

        # Local for high-volume tasks
        unit_tester:
          mode: local
          provider: ollama
          model: qwen3:8b
```

---

## Performance Tips

### 1. Choose Right Model Size

| RAM | Recommended Size |
|-----|------------------|
| 8GB | 3B-7B models |
| 16GB | 7B-13B models |
| 32GB+ | 13B+ models |

### 2. Use Quantized Models

Quantized models (4-bit, 8-bit) use less RAM:

```bash
# MLX example
mlx_lm.download mlx-community/Qwen2.5-Coder-7B-4bit  # vs 8bit
```

### 3. Keep Server Running

Start servers before QE sessions to avoid startup delays.

### 4. Use Appropriate Context Length

Shorter context = faster inference:

```bash
# Ollama example with context length
ollama run qwen3:8b --num-ctx 4096
```

---

## Troubleshooting

### Connection Refused

```
[INCORRECT] Connection failed: Connection refused
```

**Solution**: Ensure server is running:

```bash
# Ollama
ollama serve

# MLX
mlx_lm.server --model <model>

# LM Studio
# Check Local Server tab
```

### Model Not Found

```
[INCORRECT] Model 'qwen3:8b' not found
```

**Solution**: Pull/download the model first:

```bash
# Ollama
ollama pull qwen3:8b

# MLX
mlx_lm.download mlx-community/Qwen2.5-Coder-3B-4bit
```

### Out of Memory

```
[INCORRECT] CUDA out of memory / MPS out of memory
```

**Solutions**:
- Use smaller model
- Use quantized model
- Close other applications
- Reduce context length

### Slow Inference

**Solutions**:
- Use quantized models
- Reduce context length
- Use GPU acceleration
- Consider faster hardware

---

## Comparison

| Provider | Setup | Speed | GUI | Best For |
|----------|-------|-------|-----|----------|
| Ollama | Easy | Fast | No | General use |
| LM Studio | Easy | Medium | Yes | Beginners |
| MLX | Medium | Fast | No | Apple Silicon |
| vLLM | Advanced | Very Fast | No | Production |
| SGLang | Medium | Very Fast | No | Structured generation |
| TGI | Advanced | Very Fast | No | Multi-GPU production |
| llama.cpp | Medium | Medium | No | CPU inference |

---

## Next Steps

- [BYOK Providers](byok.md) - Cloud alternatives
- [Provider Commands](../cli-reference/provider-commands.md) - CLI reference
- [Team Configuration](../configuration/team.md) - Role setup
