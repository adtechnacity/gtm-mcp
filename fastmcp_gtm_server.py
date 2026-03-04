#!/usr/bin/env python3
"""
FastMCP GTM Server — MCP server exposing Google Tag Manager API v2 as tools.

Provides 18 tools for managing GTM accounts, containers, workspaces, tags,
triggers, variables, consent settings, and publishing. Uses Google Service
Account credentials via gtm_client_fixed.GTMClient for authentication.

Read tools are defined here; write tools are in fastmcp_gtm_write_tools.
Shared helpers live in fastmcp_gtm_helpers.

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS: Path to Google service account JSON key file

Run directly:
    uv run python fastmcp_gtm_server.py

Or via entry point:
    mcp-gtm-server
"""
import asyncio

from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run, logger,
    HAS_GTM_COMPONENTS,
    _validate_ids, _paginated_list, _resolve_workspace_parent,
)

try:
    from gtm_components import GTMComponentTemplates
except ImportError:
    pass

# Import write tools so they register on the shared mcp instance
import fastmcp_gtm_write_tools  # noqa: F401


# ---------------------------------------------------------------------------
# Read / query tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def test_gtm_connection(account_id: str) -> dict:
    """Test GTM API connection and authentication.

    Verifies service account credentials are valid by listing containers in the given account.
    Returns connection status and up to 5 container names. Use this to confirm
    credentials work before running other tools.

    Args:
        account_id: GTM Account ID (numeric string, e.g. "123456")
    """
    try:
        error = _validate_ids(account_id=account_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        containers = await asyncio.to_thread(client.list_containers, account_id)

        return {
            "status": "success",
            "message": "GTM API connection successful",
            "account_id": account_id,
            "containers_found": len(containers),
            "containers": [{"name": c.get("name", "Unknown"), "containerId": c.get("containerId", "Unknown")} for c in containers[:5]]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"GTM connection failed: {str(e)}"
        }

@mcp.tool()
async def list_gtm_containers(account_id: str) -> dict:
    """List all GTM containers in an account.

    Calls tagmanager.accounts.containers.list. Returns container names, IDs,
    public IDs, and usage contexts. Use this to discover container IDs needed
    by most other tools.

    Args:
        account_id: GTM Account ID (numeric string)
    """
    try:
        error = _validate_ids(account_id=account_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        containers = await asyncio.to_thread(client.list_containers, account_id)

        return {
            "status": "success",
            "account_id": account_id,
            "total_containers": len(containers),
            "containers": containers
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list containers: {str(e)}"
        }

@mcp.tool()
async def list_gtm_accounts() -> dict:
    """List all GTM accounts the authenticated user has access to.

    Calls tagmanager.accounts.list. Returns each account's name, ID, and path.
    This is typically the first discovery call — use the returned account IDs
    with list_gtm_containers to find containers.
    """
    try:
        client = get_gtm_client()

        result = await _run(client.service.accounts().list())

        accounts = result.get('account', [])

        return {
            "status": "success",
            "total_accounts": len(accounts),
            "accounts": [
                {
                    "name": a.get('name'),
                    "accountId": a.get('accountId'),
                    "path": a.get('path')
                }
                for a in accounts
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list accounts: {str(e)}"
        }


@mcp.tool()
async def list_gtm_workspaces(account_id: str, container_id: str) -> dict:
    """List all workspaces in a GTM container.

    Calls tagmanager.accounts.containers.workspaces.list.
    Returns each workspace's name, ID, and description. The workspace ID is
    required by most tools that modify container contents.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}"

        workspaces = await _paginated_list(
            lambda **kw: client.service.accounts().containers().workspaces().list(parent=parent, **kw),
            'workspace'
        )

        return {
            "status": "success",
            "total_workspaces": len(workspaces),
            "workspaces": [
                {
                    "name": w.get('name'),
                    "workspaceId": w.get('workspaceId'),
                    "description": w.get('description', '')
                }
                for w in workspaces
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list workspaces: {str(e)}"
        }

@mcp.tool()
async def list_gtm_variables(account_id: str, container_id: str, workspace_id: str = "1") -> dict:
    """List all variables in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.variables.list.
    Returns each variable's name, type, and ID.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        variables = await _paginated_list(
            lambda **kw: client.service.accounts().containers().workspaces().variables().list(parent=parent, **kw),
            'variable'
        )

        return {
            "status": "success",
            "total_variables": len(variables),
            "variables": [
                {
                    "name": v.get('name'),
                    "type": v.get('type'),
                    "variableId": v.get('variableId')
                }
                for v in variables
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list variables: {str(e)}"
        }

@mcp.tool()
async def list_gtm_tags(account_id: str, container_id: str, workspace_id: str = "1") -> dict:
    """List all tags in a GTM workspace, including their consent settings.

    Calls tagmanager.accounts.containers.workspaces.tags.list.
    Returns each tag's name, type, ID, firing/blocking triggers, pause state,
    and parsed consent configuration. Use this to audit which tags have consent
    requirements configured.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        tags = await _paginated_list(
            lambda **kw: client.service.accounts().containers().workspaces().tags().list(parent=parent, **kw),
            'tag'
        )

        def parse_consent_settings(tag):
            cs = tag.get('consentSettings', {})
            consent_status = cs.get('consentStatus', 'notSet')
            consent_type_param = cs.get('consentType', {})
            if consent_type_param.get('type') == 'list':
                consent_types = [item.get('value', '') for item in consent_type_param.get('list', [])]
            else:
                consent_types = []
            return {
                "consentStatus": consent_status,
                "consentTypes": consent_types
            }

        return {
            "status": "success",
            "total_tags": len(tags),
            "tags": [
                {
                    "name": t.get('name'),
                    "type": t.get('type'),
                    "tagId": t.get('tagId'),
                    "paused": t.get('paused', False),
                    "firingTriggerId": t.get('firingTriggerId', []),
                    "blockingTriggerId": t.get('blockingTriggerId', []),
                    "consentSettings": parse_consent_settings(t),
                    "tagManagerUrl": t.get('tagManagerUrl', '')
                }
                for t in tags
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list tags: {str(e)}"
        }


@mcp.tool()
async def get_gtm_tag(account_id: str, container_id: str, tag_id: str, workspace_id: str = "1") -> dict:
    """Get full details of a specific GTM tag, including all parameters and consent settings.

    Calls tagmanager.accounts.containers.workspaces.tags.get.
    Returns the complete tag resource with all fields (parameters, consent
    settings, firing triggers, etc.).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to retrieve
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        path = f"{ws_parent}/tags/{tag_id}"

        tag = await _run(client.service.accounts().containers().workspaces().tags().get(
            path=path
        ))

        return {
            "status": "success",
            "tag": tag
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get tag: {str(e)}"
        }


@mcp.tool()
async def list_gtm_triggers(account_id: str, container_id: str, workspace_id: str = "1") -> dict:
    """List all triggers in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.triggers.list.
    Returns each trigger's name, type, ID, filter conditions, and custom event filters.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        triggers = await _paginated_list(
            lambda **kw: client.service.accounts().containers().workspaces().triggers().list(parent=parent, **kw),
            'trigger'
        )

        return {
            "status": "success",
            "total_triggers": len(triggers),
            "triggers": [
                {
                    "name": t.get('name'),
                    "type": t.get('type'),
                    "triggerId": t.get('triggerId'),
                    "filter": t.get('filter', []),
                    "customEventFilter": t.get('customEventFilter', [])
                }
                for t in triggers
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list triggers: {str(e)}"
        }


@mcp.tool()
async def delete_gtm_variable(account_id: str, container_id: str, variable_id: str, workspace_id: str = "1") -> dict:
    """Delete a variable from a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.variables.delete.
    This is permanent within the workspace — publish to make it live, or
    discard workspace changes to undo.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variable_id: The variable ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, variable_id=variable_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        path = f"{ws_parent}/variables/{variable_id}"

        await _run(client.service.accounts().containers().workspaces().variables().delete(
            path=path
        ))

        return {
            "status": "success",
            "message": f"Variable {variable_id} deleted successfully"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete variable: {str(e)}"
        }

@mcp.tool()
async def generate_ga4_template(measurement_id: str, config_parameters: dict = None) -> dict:
    """Generate a GA4 tag template as JSON without creating anything in GTM.

    Returns a JSON template for a GA4 configuration tag that can be reviewed,
    modified, or manually imported. No API calls are made. Uses
    GTMComponentTemplates.google_analytics_4_tag() locally.

    Args:
        measurement_id: GA4 Measurement ID (e.g. "G-XXXXXXXXXX")
        config_parameters: Optional dict of additional GA4 config parameters
    """
    try:
        if not HAS_GTM_COMPONENTS:
            return {"status": "error", "message": "GTM components not available"}

        if config_parameters is None:
            config_parameters = {}

        ga4_tag = GTMComponentTemplates.google_analytics_4_tag(measurement_id, config_parameters)

        return {
            "status": "success",
            "template_type": "GA4 Configuration Tag",
            "measurement_id": measurement_id,
            "template": ga4_tag,
            "usage": "Copy this JSON template and import it into your GTM container"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to generate GA4 template: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for the MCP GTM server."""
    logger.info("Starting FastMCP GTM Server...")
    mcp.run()


if __name__ == '__main__':
    main()
