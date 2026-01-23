"""HuggingFace Inference Endpoints client for dedicated deployments.

This module provides access to HuggingFace Inference Endpoints,
allowing users to connect to their dedicated model deployments.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# HuggingFace Inference Endpoints API
HF_ENDPOINTS_API = "https://api.endpoints.huggingface.cloud/v2"


class EndpointState(Enum):
    """Possible states for an Inference Endpoint."""

    PENDING = "pending"
    INITIALIZING = "initializing"
    UPDATING = "updating"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    SCALED_TO_ZERO = "scaledToZero"


class EndpointType(Enum):
    """Types of Inference Endpoints."""

    PROTECTED = "protected"  # Requires HF token
    PUBLIC = "public"  # Anyone can access
    PRIVATE = "private"  # Private VPC


@dataclass
class InferenceEndpoint:
    """Represents an HF Inference Endpoint.

    Attributes:
        name: Endpoint name
        model_id: Deployed model ID
        url: Endpoint URL for inference
        state: Current endpoint state
        type: Endpoint type (protected, public, private)
        instance_type: Hardware instance type
        instance_size: Instance size configuration
        region: Deployment region
        created_at: Creation timestamp
        updated_at: Last update timestamp
        revision: Model revision/commit
        framework: ML framework (pytorch, etc.)
        task: Task type (text-generation, etc.)
        scaling: Scaling configuration
    """

    name: str
    model_id: str
    url: str = ""
    state: EndpointState = EndpointState.PENDING
    type: EndpointType = EndpointType.PROTECTED
    instance_type: str = ""
    instance_size: str = ""
    region: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    revision: str = ""
    framework: str = ""
    task: str = ""
    scaling: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        """Check if endpoint is running and ready."""
        return self.state == EndpointState.RUNNING

    @property
    def is_paused(self) -> bool:
        """Check if endpoint is paused."""
        return self.state in (EndpointState.PAUSED, EndpointState.SCALED_TO_ZERO)


@dataclass
class EndpointResponse:
    """Response from an Inference Endpoint.

    Attributes:
        content: Generated text
        model: Model ID
        usage: Token usage
        error: Error message if failed
    """

    content: str = ""
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    error: str = ""


class HFEndpointsClient:
    """HuggingFace Inference Endpoints client.

    Provides access to dedicated Inference Endpoints for production deployments.

    Environment:
        HF_TOKEN: Required for accessing endpoints API and protected endpoints
    """

    def __init__(self, token: Optional[str] = None, namespace: Optional[str] = None):
        """Initialize the Endpoints client.

        Args:
            token: HF token. Falls back to HF_TOKEN env var.
            namespace: HF organization/username namespace.
        """
        self._token = (
            token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        )
        self._namespace = namespace

    @property
    def is_authenticated(self) -> bool:
        """Check if we have authentication."""
        return self._token is not None and len(self._token) > 0

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Make a request to the Endpoints API.

        Args:
            method: HTTP method.
            endpoint: API endpoint.
            data: Request body.
            timeout: Request timeout.

        Returns:
            JSON response.
        """
        url = f"{HF_ENDPOINTS_API}{endpoint}"

        headers = {
            "Accept": "application/json",
        }

        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        body = None
        if data:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)

        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _async_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._request(method, endpoint, data, timeout)
        )

    async def list_endpoints(self, namespace: Optional[str] = None) -> List[InferenceEndpoint]:
        """List all Inference Endpoints.

        Args:
            namespace: Filter by namespace (organization/username).

        Returns:
            List of InferenceEndpoint objects.
        """
        if not self.is_authenticated:
            return []

        try:
            ns = namespace or self._namespace
            endpoint_url = "/endpoint"
            if ns:
                endpoint_url = f"/endpoint?namespace={ns}"

            response = await self._async_request("GET", endpoint_url)

            endpoints = []
            items = response.get("items", response) if isinstance(response, dict) else response

            for item in items:
                endpoints.append(self._parse_endpoint(item))

            return endpoints

        except HTTPError as e:
            if e.code == 401:
                return []  # Not authenticated
            raise
        except Exception:
            return []

    async def get_endpoint(
        self, name: str, namespace: Optional[str] = None
    ) -> Optional[InferenceEndpoint]:
        """Get a specific Inference Endpoint.

        Args:
            name: Endpoint name.
            namespace: Namespace (organization/username).

        Returns:
            InferenceEndpoint or None if not found.
        """
        if not self.is_authenticated:
            return None

        ns = namespace or self._namespace
        if not ns:
            # Try to find from list
            endpoints = await self.list_endpoints()
            for ep in endpoints:
                if ep.name == name:
                    return ep
            return None

        try:
            response = await self._async_request("GET", f"/endpoint/{ns}/{name}")
            return self._parse_endpoint(response)
        except HTTPError as e:
            if e.code == 404:
                return None
            raise
        except Exception:
            return None

    async def get_endpoint_status(
        self, name: str, namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get the status of an Inference Endpoint.

        Args:
            name: Endpoint name.
            namespace: Namespace.

        Returns:
            Status dictionary.
        """
        endpoint = await self.get_endpoint(name, namespace)

        if not endpoint:
            return {
                "available": False,
                "error": "Endpoint not found",
            }

        return {
            "available": endpoint.is_running,
            "state": endpoint.state.value,
            "url": endpoint.url,
            "model": endpoint.model_id,
            "paused": endpoint.is_paused,
        }

    async def chat(
        self,
        endpoint_url: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        tools: Optional[List[Dict]] = None,
    ) -> EndpointResponse:
        """Send a chat completion request to an endpoint.

        Args:
            endpoint_url: Full endpoint URL.
            messages: Chat messages.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            tools: Tool definitions for function calling.

        Returns:
            EndpointResponse with generated content.
        """
        payload: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        try:
            # Endpoints use OpenAI-compatible format
            chat_url = endpoint_url.rstrip("/") + "/v1/chat/completions"

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"

            body = json.dumps(payload).encode("utf-8")
            request = Request(chat_url, data=body, headers=headers, method="POST")

            loop = asyncio.get_event_loop()

            def do_request():
                with urlopen(request, timeout=120.0) as response:
                    return json.loads(response.read().decode("utf-8"))

            response = await loop.run_in_executor(None, do_request)

            return self._parse_chat_response(response)

        except HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass

            return EndpointResponse(error=f"HTTP {e.code}: {error_body or e.reason}")

        except Exception as e:
            return EndpointResponse(error=str(e))

    def _parse_endpoint(self, data: Dict[str, Any]) -> InferenceEndpoint:
        """Parse endpoint data from API response."""
        # Parse state
        state_str = data.get("status", {}).get("state", "pending")
        try:
            state = EndpointState(state_str.lower().replace("-", "_"))
        except ValueError:
            state = EndpointState.PENDING

        # Parse type
        type_str = data.get("type", "protected")
        try:
            endpoint_type = EndpointType(type_str.lower())
        except ValueError:
            endpoint_type = EndpointType.PROTECTED

        # Parse timestamps
        created_at = None
        updated_at = None
        if "createdAt" in data:
            try:
                created_at = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
            except Exception:
                pass
        if "updatedAt" in data:
            try:
                updated_at = datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00"))
            except Exception:
                pass

        # Get model info
        model_info = data.get("model", {})
        model_id = model_info.get("repository", "")
        revision = model_info.get("revision", "")
        framework = model_info.get("framework", "")
        task = model_info.get("task", "")

        # Get compute info
        compute = data.get("compute", {})
        instance_type = compute.get("instanceType", "")
        instance_size = compute.get("instanceSize", "")

        # Get URL
        status = data.get("status", {})
        url = status.get("url", "")

        return InferenceEndpoint(
            name=data.get("name", ""),
            model_id=model_id,
            url=url,
            state=state,
            type=endpoint_type,
            instance_type=instance_type,
            instance_size=instance_size,
            region=data.get("provider", {}).get("region", ""),
            created_at=created_at,
            updated_at=updated_at,
            revision=revision,
            framework=framework,
            task=task,
            scaling=compute.get("scaling", {}),
        )

    def _parse_chat_response(self, response: Dict[str, Any]) -> EndpointResponse:
        """Parse a chat completion response."""
        choices = response.get("choices", [])

        if not choices:
            if "error" in response:
                return EndpointResponse(
                    error=response.get("error", {}).get("message", str(response["error"]))
                )
            return EndpointResponse(error="No response choices")

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        usage = response.get("usage", {})

        return EndpointResponse(
            content=content,
            model=response.get("model", ""),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )


# Singleton instance
_endpoints_client: Optional[HFEndpointsClient] = None


def get_hf_endpoints_client() -> HFEndpointsClient:
    """Get the global HF Endpoints client instance.

    Returns:
        HFEndpointsClient instance.
    """
    global _endpoints_client
    if _endpoints_client is None:
        _endpoints_client = HFEndpointsClient()
    return _endpoints_client
