"""
GTM API client with Service Account and OAuth authentication.

Wraps the Google Tag Manager API v2 using google-api-python-client. Supports
two authentication methods:

1. Service Account — headless, no browser flow. Set GOOGLE_APPLICATION_CREDENTIALS.
2. OAuth Desktop Flow — opens browser once, caches token. Set GOOGLE_OAUTH_CLIENT_SECRET.

All methods are synchronous (google-api-python-client is blocking). Callers
in async contexts should use asyncio.to_thread() to avoid blocking the event
loop.

Scopes:
    - tagmanager.readonly: Read-only access to GTM resources
    - tagmanager.edit.containers: Read-write access to GTM containers
    - tagmanager.publish: Publish GTM container versions

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS: Path to service account JSON key file
    GOOGLE_OAUTH_CLIENT_SECRET: Path to OAuth 2.0 Desktop App client secret JSON
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Redirect Google client logs to stderr
google_logger = logging.getLogger('google.auth')
google_logger.addHandler(logging.StreamHandler(sys.stderr))

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_PATH = str(Path.home() / ".gtm-mcp" / "token.json")


def _save_oauth_token(creds, token_path: str = _DEFAULT_TOKEN_PATH):
    """Save OAuth credentials to a JSON file for reuse."""
    Path(token_path).parent.mkdir(parents=True, exist_ok=True)
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }
    if creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat()
    Path(token_path).write_text(json.dumps(token_data, indent=2))
    logger.info("OAuth token saved to %s", token_path)


def _load_oauth_token(token_path: str = _DEFAULT_TOKEN_PATH):
    """Load OAuth credentials from a cached token file. Returns None if missing or invalid."""
    if not Path(token_path).exists():
        return None
    try:
        token_data = json.loads(Path(token_path).read_text())
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )
        return creds
    except Exception as e:
        logger.warning("Failed to load cached OAuth token: %s", e)
        return None


class GTMClient:
    SCOPES = [
        'https://www.googleapis.com/auth/tagmanager.readonly',
        'https://www.googleapis.com/auth/tagmanager.edit.containers',
        'https://www.googleapis.com/auth/tagmanager.publish',
    ]

    def __init__(self, credentials_file=None, oauth_client_secret=None):
        self.credentials_file = credentials_file or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        self.oauth_client_secret = oauth_client_secret or os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')

        if self.credentials_file:
            self.auth_method = "service_account"
            logger.info("GTM Client initializing with service account credentials")
            self.service = self._build_service()
        elif self.oauth_client_secret:
            self.auth_method = "oauth"
            logger.info("GTM Client initializing with OAuth user credentials")
            self.service = self._build_service_oauth()
        else:
            raise ValueError(
                "No credentials provided. Set one of:\n"
                "  - GOOGLE_APPLICATION_CREDENTIALS: path to service account JSON key\n"
                "  - GOOGLE_OAUTH_CLIENT_SECRET: path to OAuth client secret JSON\n"
                "See README.md for setup instructions."
            )

    def _build_service(self):
        creds = service_account.Credentials.from_service_account_file(
            self.credentials_file, scopes=self.SCOPES
        )
        logger.info("Building GTM service...")
        service = build('tagmanager', 'v2', credentials=creds)
        logger.info("GTM service built successfully")
        return service

    def _build_service_oauth(self):
        """Build GTM service using OAuth desktop flow with user credentials."""
        creds = _load_oauth_token()

        if creds and creds.valid:
            logger.info("Using cached OAuth token")
        elif creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired OAuth token...")
            from google.auth.transport.requests import Request
            try:
                creds.refresh(Request())
                _save_oauth_token(creds)
                logger.info("OAuth token refreshed successfully")
            except Exception as e:
                logger.warning("Token refresh failed (%s), re-authenticating...", e)
                creds = None

        if not creds or not creds.valid:
            logger.info("Starting OAuth browser login flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                self.oauth_client_secret, scopes=self.SCOPES
            )
            creds = flow.run_local_server(port=0)
            _save_oauth_token(creds)
            logger.info("OAuth login successful, token cached")

        service = build('tagmanager', 'v2', credentials=creds)
        logger.info("GTM service built successfully (OAuth)")
        return service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _workspace_parent(account_id: str, container_id: str, workspace_id: str = "1") -> str:
        return f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"

    @staticmethod
    def _params_to_list(parameters: Dict[str, Any]) -> List[Dict[str, str]]:
        """Convert a flat {key: value} dict to GTM's parameter list format."""
        return [
            {'key': key, 'value': value, 'type': 'template'}
            for key, value in parameters.items()
        ]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_tag(self, account_id: str, container_id: str, name: str, tag_type: str, parameters: Dict[str, Any], workspace_id: str = "1") -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id, workspace_id)
        tag_body = {
            'name': name,
            'type': tag_type,
            'parameter': self._params_to_list(parameters),
        }

        logger.info("Creating tag: %s", name)
        result = self.service.accounts().containers().workspaces().tags().create(
            parent=parent, body=tag_body
        ).execute()
        logger.info("Tag created successfully: %s", result.get('name', 'Unknown'))
        return result

    def create_trigger(self, account_id: str, container_id: str, name: str, trigger_type: str, filters: List[Dict[str, Any]], workspace_id: str = "1") -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id, workspace_id)
        trigger_body = {
            'name': name,
            'type': trigger_type,
            'customEventFilter': filters,
        }

        logger.info("Creating trigger: %s", name)
        result = self.service.accounts().containers().workspaces().triggers().create(
            parent=parent, body=trigger_body
        ).execute()
        logger.info("Trigger created successfully: %s", result.get('name', 'Unknown'))
        return result

    def create_variable(self, account_id: str, container_id: str, name: str, variable_type: str, parameters: Dict[str, Any], workspace_id: str = "1") -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id, workspace_id)
        variable_body = {
            'name': name,
            'type': variable_type,
            'parameter': self._params_to_list(parameters),
        }

        logger.info("Creating variable: %s", name)
        result = self.service.accounts().containers().workspaces().variables().create(
            parent=parent, body=variable_body
        ).execute()
        logger.info("Variable created successfully: %s", result.get('name', 'Unknown'))
        return result

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_containers(self, account_id: str) -> List[Dict[str, Any]]:
        parent = f"accounts/{account_id}"
        logger.info("Listing containers for account %s", account_id)
        result = self.service.accounts().containers().list(parent=parent).execute()
        containers = result.get('container', [])
        logger.info("Found %d containers", len(containers))
        return containers

    def get_container(self, account_id: str, container_id: str) -> Dict[str, Any]:
        path = f"accounts/{account_id}/containers/{container_id}"
        logger.info("Getting container %s", container_id)
        result = self.service.accounts().containers().get(path=path).execute()
        logger.info("Retrieved container: %s", result.get('name', 'Unknown'))
        return result

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish_version(self, account_id: str, container_id: str, version_name: str, version_notes: str = "", workspace_id: str = "1") -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id, workspace_id)
        version_body = {
            'name': version_name,
            'notes': version_notes,
        }

        logger.info("Creating version: %s", version_name)
        create_result = self.service.accounts().containers().workspaces().create_version(
            path=parent, body=version_body
        ).execute()

        version_path = create_result.get('containerVersion', {}).get('path')
        if not version_path:
            raise RuntimeError(
                f"Version creation succeeded but response missing containerVersion.path: "
                f"{create_result}"
            )

        logger.info("Publishing version: %s", version_name)
        publish_result = self.service.accounts().containers().versions().publish(
            path=version_path
        ).execute()

        logger.info("Version published successfully: %s", version_name)
        return publish_result
