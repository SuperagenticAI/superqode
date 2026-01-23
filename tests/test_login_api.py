import os
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success():
    """Test successful login with valid credentials."""
    base_url = os.environ.get("SUPERQODE_LOGIN_API_URL")
    if not base_url:
        pytest.skip("Set SUPERQODE_LOGIN_API_URL to run login API tests")
    async with AsyncClient(base_url=base_url) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "securepassword123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_login_invalid_credentials():
    """Test login with invalid credentials."""
    base_url = os.environ.get("SUPERQODE_LOGIN_API_URL")
    if not base_url:
        pytest.skip("Set SUPERQODE_LOGIN_API_URL to run login API tests")
    async with AsyncClient(base_url=base_url) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": "test@example.com", "password": "wrongpassword"}
        )

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data


@pytest.mark.asyncio
async def test_login_missing_fields():
    """Test login with missing required fields."""
    base_url = os.environ.get("SUPERQODE_LOGIN_API_URL")
    if not base_url:
        pytest.skip("Set SUPERQODE_LOGIN_API_URL to run login API tests")
    async with AsyncClient(base_url=base_url) as client:
        response = await client.post("/api/v1/auth/login", json={"email": "test@example.com"})

        assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_invalid_email_format():
    """Test login with invalid email format."""
    base_url = os.environ.get("SUPERQODE_LOGIN_API_URL")
    if not base_url:
        pytest.skip("Set SUPERQODE_LOGIN_API_URL to run login API tests")
    async with AsyncClient(base_url=base_url) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": "invalid-email", "password": "password123"}
        )

        assert response.status_code == 422
