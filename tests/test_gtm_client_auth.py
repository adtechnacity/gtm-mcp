"""Tests for GTMClient auth detection logic."""
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gtm_client_fixed import GTMClient


class TestAuthDetection:
    """Test that GTMClient picks the right auth method based on env vars."""

    def test_no_credentials_raises_error(self):
        """Neither env var set -> ValueError with message about both options."""
        env = os.environ.copy()
        env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        env.pop("GOOGLE_OAUTH_CLIENT_SECRET", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="GOOGLE_APPLICATION_CREDENTIALS"):
                GTMClient()

    def test_service_account_env_var_uses_service_account(self):
        """GOOGLE_APPLICATION_CREDENTIALS set -> service account path."""
        sa_data = {
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key123",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA2a2rwplBQLfkLSMbHFzmaOY+LBxiV1EM0rnVYAVKxRLmVBbB\nm8A1Bm5JOEeqEqxz0yOG8GG05GjGJGa1iktk2oKt7bUJN17kXfh3GQBA1JaVCh8\nSPQ5DOjmVJLMNW4PG4GK1TaFbMR5pB8kxZflRB7NrQMJsFPq3e5pJgBLeeNMkNzj\nngcSd9JFy0p5LPy7LBGp9R8IZPMARNPtQGwfNOYdYKwxPMxizN2FDJBqPJgPifba\ne2XRcF0SE+1j6MNxQSVl/wPJaRfnBBm5NC9gTMGNPGxkFRX/FHBNQNMA+stJjJIv\nYEdCXQfH57KS8GhCOoeRwLDr5bGVbJJTTRZvmwIDAQABAoIBAFYqBExhVVCx2fLQ\n-----END RSA PRIVATE KEY-----\n",
            "client_email": "test@test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sa_data, f)
            sa_path = f.name

        try:
            with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": sa_path}, clear=False):
                with patch.object(GTMClient, "_build_service") as mock_build:
                    mock_build.return_value = MagicMock()
                    client = GTMClient()
                    assert client.auth_method == "service_account"
                    mock_build.assert_called_once()
        finally:
            os.unlink(sa_path)

    def test_oauth_env_var_uses_oauth(self):
        """GOOGLE_OAUTH_CLIENT_SECRET set (no SA) -> OAuth path."""
        oauth_data = {
            "installed": {
                "client_id": "test-client-id.apps.googleusercontent.com",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(oauth_data, f)
            oauth_path = f.name

        try:
            env = os.environ.copy()
            env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            env["GOOGLE_OAUTH_CLIENT_SECRET"] = oauth_path
            with patch.dict(os.environ, env, clear=True):
                with patch.object(GTMClient, "_build_service_oauth") as mock_build:
                    mock_build.return_value = MagicMock()
                    client = GTMClient()
                    assert client.auth_method == "oauth"
                    mock_build.assert_called_once()
        finally:
            os.unlink(oauth_path)

    def test_service_account_takes_priority_over_oauth(self):
        """Both env vars set -> service account wins."""
        sa_data = {
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key123",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA2a2rwplBQLfkLSMbHFzmaOY+LBxiV1EM0rnVYAVKxRLmVBbB\nm8A1Bm5JOEeqEqxz0yOG8GG05GjGJGa1iktk2oKt7bUJN17kXfh3GQBA1JaVCh8\nSPQ5DOjmVJLMNW4PG4GK1TaFbMR5pB8kxZflRB7NrQMJsFPq3e5pJgBLeeNMkNzj\nngcSd9JFy0p5LPy7LBGp9R8IZPMARNPtQGwfNOYdYKwxPMxizN2FDJBqPJgPifba\ne2XRcF0SE+1j6MNxQSVl/wPJaRfnBBm5NC9gTMGNPGxkFRX/FHBNQNMA+stJjJIv\nYEdCXQfH57KS8GhCOoeRwLDr5bGVbJJTTRZvmwIDAQABAoIBAFYqBExhVVCx2fLQ\n-----END RSA PRIVATE KEY-----\n",
            "client_email": "test@test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        oauth_data = {
            "installed": {
                "client_id": "test.apps.googleusercontent.com",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sa_data, f)
            sa_path = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(oauth_data, f)
            oauth_path = f.name

        try:
            with patch.dict(os.environ, {
                "GOOGLE_APPLICATION_CREDENTIALS": sa_path,
                "GOOGLE_OAUTH_CLIENT_SECRET": oauth_path,
            }, clear=False):
                with patch.object(GTMClient, "_build_service") as mock_build:
                    mock_build.return_value = MagicMock()
                    client = GTMClient()
                    assert client.auth_method == "service_account"
        finally:
            os.unlink(sa_path)
            os.unlink(oauth_path)


class TestOAuthTokenCache:
    """Test token save/load/refresh logic."""

    def test_token_saved_to_disk(self, tmp_path):
        """After OAuth flow, token.json is written to token_dir."""
        from gtm_client_fixed import _save_oauth_token, _load_oauth_token

        mock_creds = MagicMock()
        mock_creds.token = "access-token-123"
        mock_creds.refresh_token = "refresh-token-456"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "client-id"
        mock_creds.client_secret = "client-secret"
        mock_creds.scopes = ["https://www.googleapis.com/auth/tagmanager.readonly"]
        mock_creds.expiry = None

        token_path = tmp_path / "token.json"
        _save_oauth_token(mock_creds, str(token_path))

        assert token_path.exists()
        data = json.loads(token_path.read_text())
        assert data["refresh_token"] == "refresh-token-456"

    def test_load_token_returns_none_if_missing(self, tmp_path):
        """No token file -> returns None."""
        from gtm_client_fixed import _load_oauth_token

        result = _load_oauth_token(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_token_returns_credentials(self, tmp_path):
        """Valid token file -> returns Credentials object."""
        from gtm_client_fixed import _load_oauth_token

        token_data = {
            "token": "access-token",
            "refresh_token": "refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": ["https://www.googleapis.com/auth/tagmanager.readonly"],
        }
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps(token_data))

        creds = _load_oauth_token(str(token_path))
        assert creds is not None
        assert creds.refresh_token == "refresh-token"
