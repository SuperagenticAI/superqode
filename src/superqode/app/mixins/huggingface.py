"""Hugging Face model browsing and download helpers."""

from __future__ import annotations
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---


class HuggingFaceMixin:
    """Hugging Face hub search/download/convert helpers."""

    def _hf_cmd(self, args: str, log: ConversationLog):
        """Handle :hf command - HuggingFace Hub integration."""
        args = args.strip()
        parts = args.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if sub == "" or sub == "status":
            # :hf - Show HF status
            self._hf_status(log)
        elif sub == "search":
            # :hf search <query>
            if subargs:
                self.run_worker(self._hf_search(subargs, log))
            else:
                log.add_info("Usage: :hf search <query>")
        elif sub == "trending":
            # :hf trending - Show trending models
            self.run_worker(self._hf_trending(log))
        elif sub == "coding":
            # :hf coding - Show coding models
            self.run_worker(self._hf_coding(log))
        elif sub == "info":
            # :hf info <model_id>
            if subargs:
                self.run_worker(self._hf_info(subargs, log))
            else:
                log.add_info("Usage: :hf info <model_id>")
        elif sub == "gguf":
            # :hf gguf <model_id> - List GGUF files
            if subargs:
                self.run_worker(self._hf_gguf(subargs, log))
            else:
                log.add_info("Usage: :hf gguf <model_id>")
        elif sub == "download":
            # :hf download <model_id> [quant]
            if subargs:
                self.run_worker(self._hf_download(subargs, log))
            else:
                log.add_info("Usage: :hf download <model_id> [quantization]")
        elif sub == "endpoints":
            # :hf endpoints - List inference endpoints
            self.run_worker(self._hf_endpoints(log))
        elif sub == "recommend":
            # :hf recommend - Recommended models
            self._hf_recommend(log)
        elif sub == "transformers":
            # :hf transformers - Show transformers runner status
            self._hf_transformers_status(log)
        else:
            log.add_info(f"Unknown subcommand: {sub}")
            log.add_system(
                "Available: search, trending, coding, info, gguf, download, endpoints, recommend, transformers"
            )
    def _hf_status(self, log: ConversationLog):
        """Show HuggingFace status."""
        from superqode.providers.huggingface import get_hf_hub, get_transformers_runner

        hub = get_hf_hub()
        runner = get_transformers_runner()

        t = Text()
        t.append(f"\n  🤗 ", style=f"bold {THEME['purple']}")
        t.append("HuggingFace Status\n\n", style=f"bold {THEME['text']}")

        # Authentication
        t.append(f"  Authentication: ", style=THEME["muted"])
        if hub.is_authenticated:
            t.append("Configured (HF_TOKEN set)\n", style=f"bold {THEME['success']}")
        else:
            t.append("Not configured\n", style=THEME["warning"])
            t.append(f"    Set HF_TOKEN for private/gated models\n", style=THEME["dim"])

        # Cache directory
        t.append(f"  Cache Dir:      ", style=THEME["muted"])
        t.append(f"{hub.cache_dir}\n", style=THEME["text"])

        # Transformers availability
        t.append(f"\n  Transformers Runner:\n", style=f"bold {THEME['cyan']}")
        deps = runner.check_dependencies()
        for dep, available in deps.items():
            icon = "✓" if available else "○"
            style = THEME["success"] if available else THEME["dim"]
            t.append(f"    {icon} {dep}\n", style=style)

        if runner.is_loaded:
            t.append(f"\n  Loaded Model: ", style=THEME["muted"])
            t.append(f"{runner.loaded_model_id}\n", style=f"bold {THEME['success']}")

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":hf search <query>", style=THEME["success"])
        t.append(" to find models\n", style=THEME["muted"])

        log.write(t)
    async def _hf_search(self, query: str, log: ConversationLog):
        """Search HuggingFace Hub for models."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info(f"Searching HF Hub for '{query}'...")

        hub = get_hf_hub()
        models = await hub.search_models(query=query, limit=15)

        t = Text()
        t.append(f"\n  🤗 ", style=f"bold {THEME['purple']}")
        t.append(f"Search Results: '{query}'\n\n", style=f"bold {THEME['text']}")

        if models:
            for model in models:
                t.append(f"  ● ", style=THEME["cyan"])
                t.append(f"{model.id}\n", style=f"bold {THEME['text']}")

                t.append(f"    ", style="")
                t.append(f"↓{model.downloads_display}", style=THEME["muted"])
                t.append(f"  ♥{model.likes}", style=THEME["pink"])
                if model.is_gguf:
                    t.append(f"  [GGUF]", style=THEME["success"])
                if model.gated:
                    t.append(f"  [gated]", style=THEME["warning"])
                if model.license:
                    t.append(f"  {model.license}", style=THEME["dim"])
                t.append("\n", style="")

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(":hf info <model>", style=THEME["success"])
            t.append(" for details\n", style=THEME["muted"])
        else:
            t.append(f"  ○ No models found\n", style=THEME["muted"])

        log.write(t)
    async def _hf_trending(self, log: ConversationLog):
        """Show trending text generation models."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info("Fetching trending models...")

        hub = get_hf_hub()
        models = await hub.get_trending(limit=15)

        t = Text()
        t.append(f"\n  🔥 ", style=f"bold {THEME['orange']}")
        t.append("Trending Text Generation Models\n\n", style=f"bold {THEME['text']}")

        for i, model in enumerate(models, 1):
            t.append(f"  {i:2}. ", style=THEME["muted"])
            t.append(f"{model.id}\n", style=f"bold {THEME['text']}")
            t.append(f"      ↓{model.downloads_display}", style=THEME["dim"])
            if model.is_gguf:
                t.append(f"  [GGUF]", style=THEME["success"])
            t.append("\n", style="")

        log.write(t)
    async def _hf_coding(self, log: ConversationLog):
        """Show popular coding models."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info("Fetching coding models...")

        hub = get_hf_hub()
        models = await hub.get_popular_coding(limit=15)

        t = Text()
        t.append(f"\n  💻 ", style=f"bold {THEME['cyan']}")
        t.append("Popular Coding Models\n\n", style=f"bold {THEME['text']}")

        for model in models:
            t.append(f"  ● ", style=THEME["success"])
            t.append(f"{model.id}\n", style=f"bold {THEME['text']}")
            t.append(f"    ↓{model.downloads_display}", style=THEME["dim"])
            if model.is_gguf:
                t.append(f"  [GGUF]", style=THEME["success"])
            if model.gated:
                t.append(f"  [gated]", style=THEME["warning"])
            t.append("\n", style="")

        log.write(t)
    async def _hf_info(self, model_id: str, log: ConversationLog):
        """Show detailed info about a HF model."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info(f"Fetching info for {model_id}...")

        hub = get_hf_hub()
        model = await hub.get_model_info(model_id)

        t = Text()
        t.append(f"\n  🤗 ", style=f"bold {THEME['purple']}")
        t.append(f"Model: {model_id}\n\n", style=f"bold {THEME['text']}")

        if model:
            t.append(f"  Author:      ", style=THEME["muted"])
            t.append(f"{model.author}\n", style=THEME["text"])
            t.append(f"  Downloads:   ", style=THEME["muted"])
            t.append(f"{model.downloads:,}\n", style=THEME["text"])
            t.append(f"  Likes:       ", style=THEME["muted"])
            t.append(f"{model.likes}\n", style=THEME["text"])
            t.append(f"  License:     ", style=THEME["muted"])
            t.append(f"{model.license or 'unspecified'}\n", style=THEME["text"])
            t.append(f"  Library:     ", style=THEME["muted"])
            t.append(f"{model.library or 'unknown'}\n", style=THEME["text"])
            t.append(f"  Task:        ", style=THEME["muted"])
            t.append(f"{model.pipeline_tag or 'unknown'}\n", style=THEME["text"])

            if model.gated:
                t.append(f"\n  ⚠️  This is a gated model\n", style=THEME["warning"])
                t.append(f"     Request access at: huggingface.co/{model_id}\n", style=THEME["dim"])

            if model.is_gguf:
                t.append(f"\n  💡 ", style=THEME["muted"])
                t.append(":hf gguf", style=THEME["success"])
                t.append(f" {model_id}", style=THEME["text"])
                t.append(" to list GGUF files\n", style=THEME["muted"])
        else:
            t.append(f"  ○ Model not found\n", style=THEME["error"])

        log.write(t)
    async def _hf_gguf(self, model_id: str, log: ConversationLog):
        """List GGUF files for a model."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info(f"Fetching GGUF files for {model_id}...")

        hub = get_hf_hub()
        files = await hub.list_gguf_files(model_id)

        t = Text()
        t.append(f"\n  📦 ", style=f"bold {THEME['purple']}")
        t.append(f"GGUF Files: {model_id}\n\n", style=f"bold {THEME['text']}")

        if files:
            for f in files:
                t.append(f"  ● ", style=THEME["success"])
                t.append(f"{f.filename}\n", style=THEME["text"])
                t.append(f"    ", style="")
                t.append(f"{f.quantization}", style=f"bold {THEME['cyan']}")
                t.append(f"  {f.size_display}\n", style=THEME["muted"])

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(":hf download", style=THEME["success"])
            t.append(f" {model_id} Q4_K_M", style=THEME["text"])
            t.append(" to download\n", style=THEME["muted"])
        else:
            t.append(f"  ○ No GGUF files found\n", style=THEME["muted"])
            t.append(f"  This model may not have GGUF versions\n", style=THEME["dim"])

        log.write(t)
    async def _hf_download(self, args: str, log: ConversationLog):
        """Download a model from HuggingFace Hub."""
        from superqode.providers.huggingface import get_hf_downloader

        parts = args.split()
        model_id = parts[0]
        quantization = parts[1] if len(parts) > 1 else "Q4_K_M"

        log.add_info(f"Downloading {model_id} ({quantization})...")

        downloader = get_hf_downloader()

        def progress_callback(progress):
            if not progress.completed:
                msg = f"Downloading: {progress.progress_percent:.1f}% ({progress.speed_mbps:.1f} MB/s)"
                # This callback runs in executor thread, so we need call_from_thread
                self._call_ui(log.add_system, msg)

        result = await downloader.download_for_ollama(
            model_id, quantization=quantization, progress_callback=progress_callback
        )

        t = Text()
        if result.success:
            t.append(f"\n  ✓ ", style=f"bold {THEME['success']}")
            t.append("Download complete!\n\n", style=THEME["success"])
            t.append(f"  Path: {result.path}\n", style=THEME["text"])
            if result.ollama_model_name:
                t.append(f"\n  To use in Ollama:\n", style=THEME["muted"])
                t.append(f"    ollama create {result.ollama_model_name} -f ", style=THEME["cyan"])
                t.append(
                    f"{result.path.parent}/{result.path.stem}.Modelfile\n", style=THEME["text"]
                )
        else:
            t.append(f"\n  ✗ ", style=f"bold {THEME['error']}")
            t.append(f"Download failed: {result.error}\n", style=THEME["error"])

        log.write(t)
    async def _hf_endpoints(self, log: ConversationLog):
        """List HuggingFace Inference Endpoints."""
        from superqode.providers.huggingface import get_hf_endpoints_client

        client = get_hf_endpoints_client()

        if not client.is_authenticated:
            t = Text()
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append("HF_TOKEN not set\n", style=THEME["text"])
            t.append(f"  Set HF_TOKEN to list your Inference Endpoints\n", style=THEME["muted"])
            log.write(t)
            return

        log.add_info("Fetching Inference Endpoints...")

        endpoints = await client.list_endpoints()

        t = Text()
        t.append(f"\n  🚀 ", style=f"bold {THEME['purple']}")
        t.append("Your Inference Endpoints\n\n", style=f"bold {THEME['text']}")

        if endpoints:
            for ep in endpoints:
                status_icon = "●" if ep.is_running else "○"
                status_style = THEME["success"] if ep.is_running else THEME["dim"]

                t.append(f"  {status_icon} ", style=status_style)
                t.append(f"{ep.name}", style=f"bold {THEME['text']}")
                t.append(f"  ({ep.state.value})\n", style=THEME["muted"])
                t.append(f"    Model: {ep.model_id}\n", style=THEME["dim"])
                if ep.url:
                    t.append(f"    URL: {ep.url}\n", style=THEME["dim"])
        else:
            t.append(f"  ○ No Inference Endpoints found\n", style=THEME["muted"])
            t.append(
                f"  Create endpoints at: huggingface.co/inference-endpoints\n", style=THEME["dim"]
            )

        log.write(t)
    def _hf_recommend(self, log: ConversationLog):
        """Show recommended HF models."""
        from superqode.providers.huggingface import RECOMMENDED_MODELS

        t = Text()
        t.append(f"\n  🌟 ", style=f"bold {THEME['purple']}")
        t.append("Recommended HuggingFace Models\n\n", style=f"bold {THEME['text']}")

        categories = [
            ("general", "General Purpose", THEME["cyan"]),
            ("coding", "Coding", THEME["success"]),
            ("small", "Small/Fast", THEME["orange"]),
            ("chat", "Chat/Assistant", THEME["pink"]),
        ]

        for cat_id, cat_name, color in categories:
            models = RECOMMENDED_MODELS.get(cat_id, [])
            t.append(f"  {cat_name}:\n", style=f"bold {color}")
            for model in models[:4]:
                t.append(f"    ● {model}\n", style=THEME["text"])
            t.append("\n", style="")

        t.append(f"  💡 These work with HF Inference API (free tier)\n", style=THEME["muted"])

        self._show_command_output(log, t)
    def _hf_transformers_status(self, log: ConversationLog):
        """Show transformers runner status."""
        from superqode.providers.huggingface import get_transformers_runner

        runner = get_transformers_runner()
        deps = runner.check_dependencies()
        device = runner.get_device_info() if runner.is_available() else {}

        t = Text()
        t.append(f"\n  🔧 ", style=f"bold {THEME['purple']}")
        t.append("Transformers Runner Status\n\n", style=f"bold {THEME['text']}")

        # Dependencies
        t.append(f"  Dependencies:\n", style=f"bold {THEME['cyan']}")
        for dep, available in deps.items():
            icon = "✓" if available else "○"
            style = THEME["success"] if available else THEME["dim"]
            t.append(f"    {icon} {dep}\n", style=style)

        # Device info
        if device.get("available"):
            t.append(f"\n  Compute:\n", style=f"bold {THEME['cyan']}")
            if device.get("cuda_available"):
                t.append(
                    f"    ✓ CUDA: {device.get('cuda_device_name', 'Unknown')}\n",
                    style=THEME["success"],
                )
                t.append(
                    f"      VRAM: {device.get('cuda_memory_gb', 0):.1f}GB\n", style=THEME["dim"]
                )
            elif device.get("mps_available"):
                t.append(f"    ✓ Apple MPS (Metal) available\n", style=THEME["success"])
            else:
                t.append(f"    ○ CPU only\n", style=THEME["muted"])

        # Loaded model
        if runner.is_loaded:
            info = runner.get_loaded_info()
            t.append(f"\n  Loaded Model:\n", style=f"bold {THEME['success']}")
            t.append(f"    {info['model_id']}\n", style=THEME["text"])
            t.append(f"    Memory: {info['memory_usage_gb']:.1f}GB\n", style=THEME["dim"])
        else:
            t.append(f"\n  No model loaded\n", style=THEME["muted"])
            t.append(f"  Use :hf load <model_id> to load a model\n", style=THEME["dim"])

        if not runner.is_available():
            t.append(f"\n  ⚠️  Install dependencies:\n", style=THEME["warning"])
            t.append(f"    pip install transformers accelerate torch\n", style=THEME["cyan"])

        log.write(t)
