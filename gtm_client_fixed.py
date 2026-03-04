"""
GTM API client with Service Account authentication.

Wraps the Google Tag Manager API v2 using google-api-python-client. Uses
Google Service Account credentials for headless authentication -- no browser
flow, no token refresh dance.

All methods are synchronous (google-api-python-client is blocking). Callers
in async contexts should use asyncio.to_thread() to avoid blocking the event
loop.

Scopes:
    - tagmanager.readonly: Read-only access to GTM resources
    - tagmanager.edit.containers: Read-write access to GTM containers
    - tagmanager.publish: Publish GTM container versions

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS: Path to service account JSON key file
"""
import logging
import os
import sys
from typing import Any, Dict, List

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Redirect Google client logs to stderr
google_logger = logging.getLogger('google.auth')
google_logger.addHandler(logging.StreamHandler(sys.stderr))

logger = logging.getLogger(__name__)


class GTMClient:
    SCOPES = [
        'https://www.googleapis.com/auth/tagmanager.readonly',
        'https://www.googleapis.com/auth/tagmanager.edit.containers',
        'https://www.googleapis.com/auth/tagmanager.publish',
    ]

    def __init__(self, credentials_file=None):
        self.credentials_file = credentials_file or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if not self.credentials_file:
            raise ValueError(
                "No credentials file provided. Set GOOGLE_APPLICATION_CREDENTIALS env var "
                "or pass credentials_file to GTMClient()"
            )
        logger.info("GTM Client initializing with SA credentials: %s", self.credentials_file)
        self.service = self._build_service()

    def _build_service(self):
        creds = service_account.Credentials.from_service_account_file(
            self.credentials_file, scopes=self.SCOPES
        )
        logger.info("Building GTM service...")
        service = build('tagmanager', 'v2', credentials=creds)
        logger.info("GTM service built successfully")
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

    def create_tag(self, account_id: str, container_id: str, name: str, tag_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id)
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

    def create_trigger(self, account_id: str, container_id: str, name: str, trigger_type: str, filters: List[Dict[str, Any]]) -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id)
        trigger_body = {
            'name': name,
            'type': trigger_type,
            'filter': filters,
        }

        logger.info("Creating trigger: %s", name)
        result = self.service.accounts().containers().workspaces().triggers().create(
            parent=parent, body=trigger_body
        ).execute()
        logger.info("Trigger created successfully: %s", result.get('name', 'Unknown'))
        return result

    def create_variable(self, account_id: str, container_id: str, name: str, variable_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        parent = self._workspace_parent(account_id, container_id)
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
