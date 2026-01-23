"""HuggingFace Inference API client with streaming support.

This module provides access to the HuggingFace Inference API (serverless)
for text generation with any compatible model.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# HuggingFace Inference API endpoints
HF_INFERENCE_API = "https://api-inference.huggingface.co/models"
HF_ROUTER_API = "https://router.huggingface.co/hf"  # New router for free inference


@dataclass
class InferenceResponse:
    """Response from HF Inference API.

    Attributes:
        content: Generated text content
        model: Model that generated the response
        finish_reason: Why generation stopped
        usage: Token usage information
        tool_calls: Tool calls if any
        error: Error message if failed
    """

    content: str = ""
    model: str = ""
    finish_reason: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    tool_calls: List[Dict] = field(default_factory=list)
    error: str = ""


# Recommended models for different use cases
RECOMMENDED_MODELS = {
    "general": [
        "meta-llama/Llama-3.3-70B-Instruct",
        "Qwen/Qwen2.5-72B-Instruct",
        "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "microsoft/Phi-3.5-mini-instruct",
    ],
    "coding": [
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
        "codellama/CodeLlama-34b-Instruct-hf",
        "bigcode/starcoder2-15b-instruct-v0.1",
    ],
    "small": [
        "microsoft/Phi-3.5-mini-instruct",
        "google/gemma-2-2b-it",
        "Qwen/Qwen2.5-3B-Instruct",
        "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    ],
    "chat": [
        "meta-llama/Llama-3.2-3B-Instruct",
        "HuggingFaceH4/zephyr-7b-beta",
        "openchat/openchat-3.5-0106",
        "NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
    ],
}


class HFInferenceClient:
    """HuggingFace Inference API client.

    Provides access to HF's serverless inference API for text generation.
    Supports both the free tier and Pro tier.

    Environment:
        HF_TOKEN: HuggingFace token for authentication (optional but recommended)
        HF_INFERENCE_ENDPOINT: Custom inference endpoint (optional)
    """

    def __init__(
        self, token: Optional[str] = None, endpoint: Optional[str] = None, use_router: bool = True
    ):
        """Initialize the Inference API client.

        Args:
            token: HF token. Falls back to HF_TOKEN env var.
            endpoint: Custom inference endpoint. Falls back to HF_INFERENCE_ENDPOINT.
            use_router: Use the new router API for better availability.
        """
        self._token = (
            token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        )
        self._custom_endpoint = endpoint or os.environ.get("HF_INFERENCE_ENDPOINT")
        self._use_router = use_router

    @property
    def is_authenticated(self) -> bool:
        """Check if we have authentication."""
        return self._token is not None and len(self._token) > 0

    def get_endpoint(self, model_id: str) -> str:
        """Get the API endpoint for a model.

        Args:
            model_id: Model ID.

        Returns:
            Full API endpoint URL.
        """
        if self._custom_endpoint:
            return f"{self._custom_endpoint}/{model_id}"

        if self._use_router:
            return f"{HF_ROUTER_API}/{model_id}/v1/chat/completions"

        return f"{HF_INFERENCE_API}/{model_id}"

    def _request(
        self, endpoint: str, data: Dict[str, Any], timeout: float = 120.0
    ) -> Dict[str, Any]:
        """Make a request to the Inference API.

        Args:
            endpoint: Full API endpoint URL.
            data: Request body.
            timeout: Request timeout.

        Returns:
            JSON response.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        body = json.dumps(data).encode("utf-8")
        request = Request(endpoint, data=body, headers=headers, method="POST")

        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _async_request(
        self, endpoint: str, data: Dict[str, Any], timeout: float = 120.0
    ) -> Dict[str, Any]:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._request(endpoint, data, timeout))

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "meta-llama/Llama-3.3-70B-Instruct",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.9,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> InferenceResponse:
        """Send a chat completion request.

        Args:
            messages: Chat messages in OpenAI format.
            model: Model ID to use.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            top_p: Nucleus sampling threshold.
            tools: Tool definitions for function calling.
            tool_choice: Tool choice mode ("auto", "none", "required").
            stream: Whether to stream the response (not yet implemented).

        Returns:
            InferenceResponse with generated content.
        """
        endpoint = self.get_endpoint(model)

        # Build request payload
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,  # Streaming handled separately
        }

        if tools:
            payload["tools"] = tools

        if tool_choice:
            payload["tool_choice"] = tool_choice

        try:
            response = await self._async_request(endpoint, payload)
            return self._parse_chat_response(response, model)

        except HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass

            return InferenceResponse(model=model, error=f"HTTP {e.code}: {error_body or e.reason}")

        except Exception as e:
            return InferenceResponse(model=model, error=str(e))

    async def generate(
        self,
        prompt: str,
        model: str = "meta-llama/Llama-3.3-70B-Instruct",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
    ) -> InferenceResponse:
        """Send a text generation request (non-chat format).

        This uses the older text generation API format for models
        that don't support chat templates.

        Args:
            prompt: Text prompt.
            model: Model ID.
            max_tokens: Maximum tokens.
            temperature: Sampling temperature.
            stop: Stop sequences.

        Returns:
            InferenceResponse with generated text.
        """
        # Use direct inference API for non-chat models
        endpoint = f"{HF_INFERENCE_API}/{model}"

        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "return_full_text": False,
            },
        }

        if stop:
            payload["parameters"]["stop_sequences"] = stop

        try:
            response = await self._async_request(endpoint, payload)

            # Parse text generation response
            if isinstance(response, list) and len(response) > 0:
                text = response[0].get("generated_text", "")
                return InferenceResponse(content=text, model=model)

            return InferenceResponse(model=model, error="Unexpected response format")

        except Exception as e:
            return InferenceResponse(model=model, error=str(e))

    async def check_model_status(self, model: str) -> Dict[str, Any]:
        """Check the status of a model on the Inference API.

        Args:
            model: Model ID.

        Returns:
            Dict with status information.
        """
        # Try a minimal request to check status
        try:
            response = await self.chat(
                messages=[{"role": "user", "content": "Hi"}],
                model=model,
                max_tokens=1,
            )

            if response.error:
                # Check for common error patterns
                if "loading" in response.error.lower():
                    return {
                        "available": False,
                        "loading": True,
                        "error": "Model is loading",
                    }
                if "rate limit" in response.error.lower():
                    return {
                        "available": True,
                        "rate_limited": True,
                        "error": response.error,
                    }
                return {
                    "available": False,
                    "error": response.error,
                }

            return {
                "available": True,
                "loading": False,
            }

        except Exception as e:
            return {
                "available": False,
                "error": str(e),
            }

    async def list_available_models(self) -> List[str]:
        """Get list of recommended available models.

        Returns:
            List of model IDs known to work well with the Inference API.
        """
        # Return all recommended models
        all_models = []
        for category_models in RECOMMENDED_MODELS.values():
            all_models.extend(category_models)

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for m in all_models:
            if m not in seen:
                seen.add(m)
                unique.append(m)

        return unique

    def get_recommended_models(self, category: str = "general") -> List[str]:
        """Get recommended models for a category.

        Args:
            category: Model category (general, coding, small, chat).

        Returns:
            List of recommended model IDs.
        """
        return RECOMMENDED_MODELS.get(category, RECOMMENDED_MODELS["general"])

    def _parse_chat_response(self, response: Dict[str, Any], model: str) -> InferenceResponse:
        """Parse a chat completion response."""
        # Handle OpenAI-compatible format
        choices = response.get("choices", [])

        if not choices:
            # Check for error
            if "error" in response:
                return InferenceResponse(
                    model=model,
                    error=response.get("error", {}).get("message", str(response["error"])),
                )
            return InferenceResponse(model=model, error="No response choices")

        choice = choices[0]
        message = choice.get("message", {})

        content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])
        finish_reason = choice.get("finish_reason", "")

        # Parse usage
        usage = response.get("usage", {})

        return InferenceResponse(
            content=content,
            model=model,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            tool_calls=tool_calls,
        )


# Singleton instance
_inference_client: Optional[HFInferenceClient] = None


def get_hf_inference_client() -> HFInferenceClient:
    """Get the global HF Inference API client instance.

    Returns:
        HFInferenceClient instance.
    """
    global _inference_client
    if _inference_client is None:
        _inference_client = HFInferenceClient()
    return _inference_client
