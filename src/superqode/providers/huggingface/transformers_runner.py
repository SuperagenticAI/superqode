"""Local transformers runner for pure Python inference.

This module provides the ability to run HuggingFace models locally
using the transformers library without requiring Ollama or other
external servers.

Requires optional dependencies:
    pip install superqode[transformers]

Or manually:
    pip install transformers accelerate torch
"""

import asyncio
import gc
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class TransformersConfig:
    """Configuration for transformers model loading.

    Attributes:
        quantization: Quantization mode ("4bit", "8bit", None)
        device_map: Device mapping strategy ("auto", "cpu", "cuda", etc.)
        torch_dtype: Data type ("float16", "bfloat16", "float32", "auto")
        max_memory: Max memory per device (e.g., {"cuda:0": "10GB"})
        trust_remote_code: Allow executing model's custom code
        use_flash_attention: Enable Flash Attention 2 if available
        low_cpu_mem_usage: Reduce CPU memory during loading
    """

    quantization: Optional[str] = None
    device_map: str = "auto"
    torch_dtype: str = "auto"
    max_memory: Optional[Dict[str, str]] = None
    trust_remote_code: bool = False
    use_flash_attention: bool = True
    low_cpu_mem_usage: bool = True


@dataclass
class GenerationResult:
    """Result from text generation.

    Attributes:
        content: Generated text
        model_id: Model used
        input_tokens: Number of input tokens
        output_tokens: Number of generated tokens
        time_seconds: Generation time
        tokens_per_second: Generation speed
        error: Error message if failed
    """

    content: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    time_seconds: float = 0.0
    tokens_per_second: float = 0.0
    error: str = ""


@dataclass
class LoadedModel:
    """Information about a loaded model.

    Attributes:
        model_id: HuggingFace model ID
        model: The loaded model object
        tokenizer: The loaded tokenizer
        config: Loading configuration used
        memory_usage_gb: Estimated GPU memory usage
    """

    model_id: str
    model: Any = None
    tokenizer: Any = None
    config: TransformersConfig = field(default_factory=TransformersConfig)
    memory_usage_gb: float = 0.0


class TransformersRunner:
    """Run HuggingFace models locally using transformers.

    This class provides a pure Python way to run models without
    external servers like Ollama. It handles model loading, caching,
    and generation with support for:

    - 4-bit and 8-bit quantization via bitsandbytes
    - Automatic device mapping (CPU/GPU)
    - Flash Attention 2 when available
    - Memory-efficient loading

    Example:
        runner = TransformersRunner()
        await runner.load_model("microsoft/Phi-3.5-mini-instruct")

        response = await runner.generate(
            messages=[{"role": "user", "content": "Hello!"}]
        )
        print(response.content)

        await runner.unload()
    """

    def __init__(self):
        """Initialize the transformers runner."""
        self._loaded: Optional[LoadedModel] = None
        self._dependencies_checked = False
        self._available_deps: Dict[str, bool] = {}

    @property
    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self._loaded is not None and self._loaded.model is not None

    @property
    def loaded_model_id(self) -> Optional[str]:
        """Get the ID of the currently loaded model."""
        return self._loaded.model_id if self._loaded else None

    def check_dependencies(self) -> Dict[str, bool]:
        """Check which transformers dependencies are available.

        Returns:
            Dict mapping dependency name to availability.
        """
        if self._dependencies_checked:
            return self._available_deps

        deps = {
            "transformers": False,
            "torch": False,
            "accelerate": False,
            "bitsandbytes": False,
            "flash_attn": False,
        }

        try:
            import transformers

            deps["transformers"] = True
        except ImportError:
            pass

        try:
            import torch

            deps["torch"] = True
        except ImportError:
            pass

        try:
            import accelerate

            deps["accelerate"] = True
        except ImportError:
            pass

        try:
            import bitsandbytes

            deps["bitsandbytes"] = True
        except ImportError:
            pass

        try:
            import flash_attn

            deps["flash_attn"] = True
        except ImportError:
            pass

        self._available_deps = deps
        self._dependencies_checked = True
        return deps

    def is_available(self) -> bool:
        """Check if transformers runner can be used.

        Returns:
            True if required dependencies are available.
        """
        deps = self.check_dependencies()
        return deps["transformers"] and deps["torch"]

    def get_device_info(self) -> Dict[str, Any]:
        """Get information about available compute devices.

        Returns:
            Dict with device information.
        """
        deps = self.check_dependencies()

        if not deps["torch"]:
            return {
                "available": False,
                "error": "PyTorch not installed",
            }

        import torch

        info = {
            "available": True,
            "cuda_available": torch.cuda.is_available(),
            "mps_available": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
            "cpu_threads": torch.get_num_threads(),
        }

        if info["cuda_available"]:
            info["cuda_device_count"] = torch.cuda.device_count()
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
            info["cuda_memory_gb"] = torch.cuda.get_device_properties(0).total_memory / (1024**3)

        return info

    async def load_model(
        self, model_id: str, config: Optional[TransformersConfig] = None, force: bool = False
    ) -> bool:
        """Load a model for inference.

        Args:
            model_id: HuggingFace model ID.
            config: Loading configuration.
            force: Force reload even if model is already loaded.

        Returns:
            True if loading succeeded.
        """
        # Check if already loaded
        if self.is_loaded and self._loaded.model_id == model_id and not force:
            return True

        # Unload existing model
        if self.is_loaded:
            await self.unload()

        deps = self.check_dependencies()
        if not deps["transformers"] or not deps["torch"]:
            return False

        config = config or TransformersConfig()

        # Run loading in executor to not block
        loop = asyncio.get_event_loop()
        loaded = await loop.run_in_executor(None, lambda: self._load_model_sync(model_id, config))

        if loaded:
            self._loaded = loaded
            return True

        return False

    def _load_model_sync(self, model_id: str, config: TransformersConfig) -> Optional[LoadedModel]:
        """Synchronous model loading."""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            # Get HF token
            token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

            # Build loading kwargs
            model_kwargs: Dict[str, Any] = {
                "device_map": config.device_map,
                "low_cpu_mem_usage": config.low_cpu_mem_usage,
                "trust_remote_code": config.trust_remote_code,
            }

            if token:
                model_kwargs["token"] = token

            # Handle torch dtype
            if config.torch_dtype == "auto":
                model_kwargs["torch_dtype"] = "auto"
            elif config.torch_dtype == "float16":
                model_kwargs["torch_dtype"] = torch.float16
            elif config.torch_dtype == "bfloat16":
                model_kwargs["torch_dtype"] = torch.bfloat16
            elif config.torch_dtype == "float32":
                model_kwargs["torch_dtype"] = torch.float32

            # Handle quantization
            if config.quantization and self._available_deps.get("bitsandbytes"):
                from transformers import BitsAndBytesConfig

                if config.quantization == "4bit":
                    model_kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,
                    )
                elif config.quantization == "8bit":
                    model_kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_8bit=True,
                    )

            # Handle max memory
            if config.max_memory:
                model_kwargs["max_memory"] = config.max_memory

            # Handle flash attention
            if config.use_flash_attention and self._available_deps.get("flash_attn"):
                model_kwargs["attn_implementation"] = "flash_attention_2"

            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_id,
                token=token,
                trust_remote_code=config.trust_remote_code,
            )

            # Load model
            model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)

            # Estimate memory usage
            memory_gb = 0.0
            if torch.cuda.is_available():
                memory_gb = torch.cuda.memory_allocated() / (1024**3)

            return LoadedModel(
                model_id=model_id,
                model=model,
                tokenizer=tokenizer,
                config=config,
                memory_usage_gb=memory_gb,
            )

        except Exception as e:
            print(f"Error loading model: {e}")
            return None

    async def generate(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
        stop: Optional[List[str]] = None,
    ) -> GenerationResult:
        """Generate text from messages.

        Args:
            messages: Chat messages in OpenAI format.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            top_p: Nucleus sampling threshold.
            top_k: Top-k sampling.
            stop: Stop sequences.

        Returns:
            GenerationResult with generated text.
        """
        if not self.is_loaded:
            return GenerationResult(error="No model loaded")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._generate_sync(messages, max_tokens, temperature, top_p, top_k, stop)
        )

    def _generate_sync(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        stop: Optional[List[str]],
    ) -> GenerationResult:
        """Synchronous generation."""
        import time
        import torch

        try:
            model = self._loaded.model
            tokenizer = self._loaded.tokenizer
            model_id = self._loaded.model_id

            # Apply chat template
            if hasattr(tokenizer, "apply_chat_template"):
                prompt = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            else:
                # Fallback for models without chat template
                prompt = (
                    "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant:"
                )

            # Tokenize
            inputs = tokenizer(prompt, return_tensors="pt")
            input_length = inputs["input_ids"].shape[1]

            # Move to model device
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            # Build generation kwargs
            gen_kwargs = {
                "max_new_tokens": max_tokens,
                "do_sample": temperature > 0,
                "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
            }

            if temperature > 0:
                gen_kwargs["temperature"] = temperature
                gen_kwargs["top_p"] = top_p
                gen_kwargs["top_k"] = top_k

            # Handle stop sequences
            if stop:
                stop_ids = [tokenizer.encode(s, add_special_tokens=False) for s in stop]
                # Flatten for stopping_criteria would be complex, skip for now

            # Generate
            start_time = time.time()

            with torch.no_grad():
                outputs = model.generate(**inputs, **gen_kwargs)

            gen_time = time.time() - start_time

            # Decode output
            output_tokens = outputs[0][input_length:]
            output_length = len(output_tokens)

            generated_text = tokenizer.decode(output_tokens, skip_special_tokens=True)

            # Calculate speed
            tokens_per_sec = output_length / gen_time if gen_time > 0 else 0

            return GenerationResult(
                content=generated_text.strip(),
                model_id=model_id,
                input_tokens=input_length,
                output_tokens=output_length,
                time_seconds=gen_time,
                tokens_per_second=tokens_per_sec,
            )

        except Exception as e:
            return GenerationResult(
                model_id=self._loaded.model_id if self._loaded else "", error=str(e)
            )

    async def unload(self) -> None:
        """Unload the current model and free memory."""
        if not self.is_loaded:
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._unload_sync)

    def _unload_sync(self) -> None:
        """Synchronous unload."""
        if self._loaded:
            # Delete model references
            if self._loaded.model is not None:
                del self._loaded.model
            if self._loaded.tokenizer is not None:
                del self._loaded.tokenizer

            self._loaded = None

        # Force garbage collection
        gc.collect()

        # Clear CUDA cache if available
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def get_loaded_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the currently loaded model.

        Returns:
            Dict with model info, or None if no model loaded.
        """
        if not self.is_loaded:
            return None

        return {
            "model_id": self._loaded.model_id,
            "memory_usage_gb": self._loaded.memory_usage_gb,
            "quantization": self._loaded.config.quantization,
            "device_map": self._loaded.config.device_map,
        }


# Singleton instance
_runner_instance: Optional[TransformersRunner] = None


def get_transformers_runner() -> TransformersRunner:
    """Get the global TransformersRunner instance.

    Returns:
        TransformersRunner instance.
    """
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = TransformersRunner()
    return _runner_instance
