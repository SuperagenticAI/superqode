# Gemma 4 chat template (vendored for tests)

- File: `chat_template.jinja`
- Source: https://huggingface.co/google/gemma-4-E2B-it/blob/main/chat_template.jinja
- Repository revision: 3e22461f65e89153144f8adb70e3b8c2cc9845a7
- SHA-256: 0a2c8073c878ab1da004bee933a998606537bbb62016310352c7285c3f01c5b5
- License: Apache License 2.0, as declared by the model repository
  (`license: apache-2.0`, license link https://ai.google.dev/gemma/docs/gemma_4_license).
  Copyright Google LLC. The file is unmodified.

Used only by `tests/test_codegem_gemma.py` to render CodeGem's local Gemma
messages with jinja2 and check tool calls, tool results, images and thinking.
It is not loaded at runtime.
