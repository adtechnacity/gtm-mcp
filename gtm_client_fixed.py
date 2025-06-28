import os
import json
import logging
import sys
from typing import Any, Dict, List, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Redirect Google client logs to stderr
google_logger = logging.getLogger('google.auth')
google_logger.addHandler(logging.StreamHandler(sys.stderr))

logger = logging.getLogger(__name__)

class GTMClient:
    SCOPES = ['https://www.googleapis.com/auth/tagmanager.edit.containers']
    
    def __init__(self, credentials_file: Optional[str] = None, token_file: Optional[str] = None):
        self.credentials_file = credentials_file or os.getenv('GTM_CREDENTIALS_FILE', 'credentials.json')
        self.token_file = token_file or os.getenv('GTM_TOKEN_FILE', 'token.json')
        self.service = None
        
        # Print authentication status to stderr (not stdout)
        print(f"GTM Client initializing with credentials: {self.credentials_file}", file=sys.stderr)
        self._authenticate()

    def _authenticate(self):
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_file):
            print(f"Loading existing token from {self.token_file}", file=sys.stderr)
            try:
                creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)
                print("Token loaded successfully", file=sys.stderr)
            except Exception as e:
                print(f"Failed to load token: {e}", file=sys.stderr)
                creds = None
        
        # Check if credentials are valid
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("Token expired, attempting refresh...", file=sys.stderr)
                try:
                    creds.refresh(Request())
                    print("Token refreshed successfully", file=sys.stderr)
                except Exception as e:
                    print(f"Token refresh failed: {e}", file=sys.stderr)
                    creds = None
            
            # If still no valid credentials, start OAuth flow
            if not creds:
                if not os.path.exists(self.credentials_file):
                    error_msg = f"Credentials file not found: {self.credentials_file}"
                    print(error_msg, file=sys.stderr)
                    raise FileNotFoundError(
                        f"{error_msg}. Please download credentials.json from Google Cloud Console."
                    )
                
                print("Starting OAuth flow...", file=sys.stderr)
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES)
                    
                    # Try to use local server for authentication
                    print("Opening browser for authentication...", file=sys.stderr)
                    creds = flow.run_local_server(
                        port=0,  # Use random available port
                        access_type='offline',
                        include_granted_scopes='true',
                        open_browser=True
                    )
                    print("Authentication successful!", file=sys.stderr)
                    
                except Exception as e:
                    error_msg = f"Authentication failed: {e}"
                    print(error_msg, file=sys.stderr)
                    raise Exception(error_msg)
            
            # Save the credentials for the next run
            print(f"Saving credentials to {self.token_file}", file=sys.stderr)
            try:
                with open(self.token_file, 'w') as token:
                    token.write(creds.to_json())
                print("Credentials saved successfully", file=sys.stderr)
            except Exception as e:
                print(f"Failed to save credentials: {e}", file=sys.stderr)

        # Build the service
        try:
            print("Building GTM service...", file=sys.stderr)
            self.service = build('tagmanager', 'v2', credentials=creds)
            print("GTM service built successfully", file=sys.stderr)
        except Exception as e:
            error_msg = f"Failed to build GTM service: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)

    async def create_tag(self, account_id: str, container_id: str, name: str, tag_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            parent = f"accounts/{account_id}/containers/{container_id}/workspaces/1"
            
            tag_body = {
                'name': name,
                'type': tag_type,
                'parameter': [
                    {'key': key, 'value': value, 'type': 'template'}
                    for key, value in parameters.items()
                ]
            }
            
            print(f"Creating tag: {name}", file=sys.stderr)
            result = self.service.accounts().containers().workspaces().tags().create(
                parent=parent,
                body=tag_body
            ).execute()
            
            print(f"Tag created successfully: {result.get('name', 'Unknown')}", file=sys.stderr)
            return result
            
        except HttpError as e:
            error_msg = f"Error creating tag {name}: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)

    async def create_trigger(self, account_id: str, container_id: str, name: str, trigger_type: str, filters: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            parent = f"accounts/{account_id}/containers/{container_id}/workspaces/1"
            
            trigger_body = {
                'name': name,
                'type': trigger_type,
                'filter': filters
            }
            
            print(f"Creating trigger: {name}", file=sys.stderr)
            result = self.service.accounts().containers().workspaces().triggers().create(
                parent=parent,
                body=trigger_body
            ).execute()
            
            print(f"Trigger created successfully: {result.get('name', 'Unknown')}", file=sys.stderr)
            return result
            
        except HttpError as e:
            error_msg = f"Error creating trigger {name}: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)

    async def create_variable(self, account_id: str, container_id: str, name: str, variable_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            parent = f"accounts/{account_id}/containers/{container_id}/workspaces/1"
            
            variable_body = {
                'name': name,
                'type': variable_type,
                'parameter': [
                    {'key': key, 'value': value, 'type': 'template'}
                    for key, value in parameters.items()
                ]
            }
            
            print(f"Creating variable: {name}", file=sys.stderr)
            result = self.service.accounts().containers().workspaces().variables().create(
                parent=parent,
                body=variable_body
            ).execute()
            
            print(f"Variable created successfully: {result.get('name', 'Unknown')}", file=sys.stderr)
            return result
            
        except HttpError as e:
            error_msg = f"Error creating variable {name}: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)

    async def list_containers(self, account_id: str) -> List[Dict[str, Any]]:
        try:
            parent = f"accounts/{account_id}"
            
            print(f"Listing containers for account {account_id}", file=sys.stderr)
            result = self.service.accounts().containers().list(parent=parent).execute()
            containers = result.get('container', [])
            
            print(f"Found {len(containers)} containers", file=sys.stderr)
            return containers
            
        except HttpError as e:
            error_msg = f"Error listing containers: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)

    async def get_container(self, account_id: str, container_id: str) -> Dict[str, Any]:
        try:
            path = f"accounts/{account_id}/containers/{container_id}"
            
            print(f"Getting container {container_id}", file=sys.stderr)
            result = self.service.accounts().containers().get(path=path).execute()
            
            print(f"Retrieved container: {result.get('name', 'Unknown')}", file=sys.stderr)
            return result
            
        except HttpError as e:
            error_msg = f"Error getting container: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)

    async def publish_version(self, account_id: str, container_id: str, version_name: str, version_notes: str = "") -> Dict[str, Any]:
        try:
            parent = f"accounts/{account_id}/containers/{container_id}/workspaces/1"
            
            version_body = {
                'name': version_name,
                'notes': version_notes
            }
            
            print(f"Creating version: {version_name}", file=sys.stderr)
            create_result = self.service.accounts().containers().workspaces().create_version(
                parent=parent,
                body=version_body
            ).execute()
            
            version_path = create_result['path']
            
            print(f"Publishing version: {version_name}", file=sys.stderr)
            publish_result = self.service.accounts().containers().versions().publish(
                path=version_path
            ).execute()
            
            print(f"Version published successfully: {version_name}", file=sys.stderr)
            return publish_result
            
        except HttpError as e:
            error_msg = f"Error publishing version: {e}"
            print(error_msg, file=sys.stderr)
            raise Exception(error_msg)