import os
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login():
    base_url = os.environ.get("SUPERQODE_LOGIN_API_URL")
    if not base_url:
        pytest.skip("Set SUPERQODE_LOGIN_API_URL to run login API tests")
    async with AsyncClient(base_url=base_url) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()
