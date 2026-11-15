# Swift MLX

Swift MLX runs cached Qwen3 text checkpoints on Apple Silicon with macOS 27 or
later. In the Mac app, open **Local AI → Start → Swift MLX**. Use an existing
checkpoint from the shared Hugging Face cache or review the starter download.
Choose **Use for chat** or **Use with Silicon Harness**.
Cached models also appear in **Local AI → Advanced → Compare**. Each
comparison records the snapshot revision and asks for a new review if it
changes before the run.

The native helper uses a private stdio protocol and loads model files from disk.
It streams text and proposes tool calls. SuperQode validates the calls and owns
tool permissions, execution, and result replay. The helper checks the rendered
prompt against the token limit and returns token usage. A worker keeps the
weights warm between nearby model turns. Cancelling a turn terminates its
helper, and the idle timeout unloads weights after the last request.

Build an app with the helper using Apple's macOS 27 SDK and Xcode Metal
Toolchain component.

```sh
SUPERQODE_INCLUDE_SWIFT_MLX=1 apps/macos/scripts/build-app.sh
```

For CLI development, build the helper and point SuperQode at the resulting binary.

```sh
export SUPERQODE_SWIFT_MLX_HELPER="$(bash apps/macos/SwiftMLX/build.sh)"
superqode harness run silicon --provider swift-mlx \
  --model mlx-community/Qwen3-0.6B-4bit --working-dir .
```

SwiftPM fetches the source dependencies recorded in `Package.resolved` during
the first build. Apple's MLX runs inference and Hugging Face's Swift Transformers
loads the tokenizer. The app bundles the executable and its Metal library. Inference
uses the cached tokenizer and weights with no Python inference packages or
model server. This route supports text and tools. The Apple on-device model
remains available for requests that need guided structured output.
