#!/usr/bin/env python3
"""
FastMCP GTM Server — MCP server exposing Google Tag Manager API v2 as tools.

Provides 33 tools for managing GTM accounts, containers, workspaces, tags,
triggers, variables, version history, consent settings, and publishing. Uses
Google Service Account credentials via gtm_client_fixed.GTMClient for
authentication.

Read tools are defined here; write tools are in fastmcp_gtm_write_tools.
Shared helpers live in fastmcp_gtm_helpers.

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS: Path to Google service account JSON key file

Run directly:
    uv run python fastmcp_gtm_server.py

Or via entry point:
    mcp-gtm-server
"""
import argparse
import asyncio
import os

from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run, logger,
    HAS_GTM_COMPONENTS,
    _validate_ids, _paginated_list, _resolve_workspace_parent,
    _fingerprint_to_iso, _summarize_version, _diff_versions,
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


# ---------------------------------------------------------------------------
# Version history tools
# ---------------------------------------------------------------------------

async def _fetch_version(client, account_id: str, container_id: str, version_id: str) -> dict:
    """Fetch a raw ContainerVersion — a numeric version_id or the special "live"."""
    parent = f"accounts/{account_id}/containers/{container_id}"
    if version_id == "live":
        return await _run(client.service.accounts().containers().versions().live(parent=parent))
    return await _run(client.service.accounts().containers().versions().get(
        path=f"{parent}/versions/{version_id}"
    ))


def _validate_version_id(name: str, version_id: str):
    """Validate a version_id parameter that also accepts the special value "live"."""
    if version_id == "live":
        return None
    return _validate_ids(**{name: version_id})


async def _get_version_summary(account_id: str, container_id: str, version_id: str) -> dict:
    """Shared fetch+summarize path for get_gtm_container_version / get_gtm_live_version."""
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    error = _validate_version_id("version_id", version_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    version = await _fetch_version(client, account_id, container_id, version_id)

    return {
        "status": "success",
        "version": _summarize_version(version)
    }


@mcp.tool()
async def list_gtm_container_versions(account_id: str, container_id: str, include_deleted: bool = False) -> dict:
    """List all container version headers (the container's publish history).

    Calls tagmanager.accounts.containers.version_headers.list.
    Returns each version's ID, name, entity counts, and deleted flag. Version
    IDs are monotonically increasing — higher ID means created later. Headers
    carry no timestamps; use get_gtm_container_version and read
    fingerprint_datetime to date a specific version.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        include_deleted: Also include deleted versions (default False)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}"

        headers = await _paginated_list(
            lambda **kw: client.service.accounts().containers().version_headers().list(
                parent=parent, includeDeleted=include_deleted, **kw),
            'containerVersionHeader'
        )

        return {
            "status": "success",
            "total_versions": len(headers),
            "versions": [
                {
                    "containerVersionId": h.get('containerVersionId'),
                    "name": h.get('name'),
                    "numTags": h.get('numTags'),
                    "numTriggers": h.get('numTriggers'),
                    "numVariables": h.get('numVariables'),
                    "deleted": h.get('deleted', False)
                }
                for h in headers
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list container versions: {str(e)}"
        }


@mcp.tool()
async def get_gtm_container_version(account_id: str, container_id: str, version_id: str) -> dict:
    """Get a summarized snapshot of a specific GTM container version.

    Calls tagmanager.accounts.containers.versions.get (or versions.live when
    version_id is "live"). Returns identity fields, entity counts, and slim
    tag/trigger/variable listings — never the raw resource, which exceeds 200KB
    on large containers. fingerprint_datetime (ISO 8601 UTC, derived from the
    version's fingerprint) is effectively the version's creation time.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        version_id: Container version ID, or "live" for the published version
    """
    try:
        return await _get_version_summary(account_id, container_id, version_id)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get container version: {str(e)}"
        }


@mcp.tool()
async def get_gtm_live_version(account_id: str, container_id: str) -> dict:
    """Get a summarized snapshot of the currently published (live) container version.

    Calls tagmanager.accounts.containers.versions.live. Same summary shape as
    get_gtm_container_version: identity fields, entity counts, slim
    tag/trigger/variable listings, and fingerprint_datetime (publish-time
    storage timestamp, ISO 8601 UTC).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
    """
    try:
        return await _get_version_summary(account_id, container_id, "live")
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get live version: {str(e)}"
        }


@mcp.tool()
async def diff_gtm_container_versions(account_id: str, container_id: str, from_version_id: str, to_version_id: str = "live") -> dict:
    """Diff two GTM container versions field-by-field, server-side.

    Calls tagmanager.accounts.containers.versions.get for each side (or
    versions.live for the special value "live"). Answers "what did publishing
    version X change" — diff X-1 → X, or X → live to see what changed since.
    Returns added/removed/changed tags, triggers, and variables (changed
    entries carry per-field change lists with GTM parameter lists matched by
    key), plus added/removed built-in variables and summary counts. Long
    string values are truncated at 300 chars; per-entity change lists are
    capped at 40 entries.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        from_version_id: Baseline version ID, or "live"
        to_version_id: Target version ID, or "live" (default)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}
        for name, version_id in (("from_version_id", from_version_id), ("to_version_id", to_version_id)):
            error = _validate_version_id(name, version_id)
            if error:
                return {"status": "error", "message": error}

        client = get_gtm_client()
        # Sequential on purpose: the googleapiclient service shares one
        # httplib2.Http, which is not thread-safe — concurrent _run calls
        # (asyncio.to_thread) could interleave on the same socket.
        from_version = await _fetch_version(client, account_id, container_id, from_version_id)
        to_version = await _fetch_version(client, account_id, container_id, to_version_id)

        def identity(version):
            return {
                "containerVersionId": version.get("containerVersionId"),
                "name": version.get("name"),
                "fingerprint_datetime": _fingerprint_to_iso(version.get("fingerprint")),
            }

        return {
            "status": "success",
            "from": identity(from_version),
            "to": identity(to_version),
            **_diff_versions(from_version, to_version)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to diff container versions: {str(e)}"
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

VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def _resolve_transport():
    """Resolve transport, host, port.

    Precedence: CLI flag > env var > default. Default is stdio, matching
    the behavior expected by Claude Desktop, `mcp-gtm-server`,
    `uv run python fastmcp_gtm_server.py`, and `./run_server.sh`.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--transport", choices=VALID_TRANSPORTS, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args, _ = parser.parse_known_args()

    transport = args.transport or os.getenv("MCP_TRANSPORT", "stdio")
    if transport not in VALID_TRANSPORTS:
        logger.warning(
            "Invalid MCP_TRANSPORT=%r; falling back to stdio. Valid: %s",
            transport, VALID_TRANSPORTS,
        )
        transport = "stdio"

    host = args.host or os.getenv("HOST", "127.0.0.1")
    port = args.port or int(os.getenv("PORT", "8000"))
    return transport, host, port


def main():
    """Entry point for the MCP GTM server.

    Default transport is stdio — no env vars needed. To run over HTTP
    (e.g. for ContextForge or any hosted gateway), set
    MCP_TRANSPORT=streamable-http and optionally HOST/PORT.
    """
    transport, host, port = _resolve_transport()

    if transport == "stdio":
        logger.info("Starting FastMCP GTM Server (stdio)...")
        mcp.run()
        return

    mcp.settings.host = host
    mcp.settings.port = port

    # The MCP SDK's DNS-rebinding protection rejects any Host header that
    # isn't localhost/127.0.0.1 with "Invalid Host header". That breaks
    # containerized deployments where a gateway reaches us via private DNS
    # (e.g. gtm-mcp.contextforge.internal). MCP_ALLOWED_HOSTS lets the
    # operator pin specific hostnames; if unset, we disable rebinding
    # protection — safe when the listener is only reachable on a private
    # network (security group, VPC, etc.).
    from mcp.server.transport_security import TransportSecuritySettings
    allowed_hosts = [
        h.strip()
        for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    allowed_origins = [
        o.strip()
        for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]
    if allowed_hosts:
        mcp.settings.transport_security = TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    else:
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    logger.info(
        "Starting FastMCP GTM Server (%s) on %s:%d...", transport, host, port
    )
    mcp.run(transport=transport)


if __name__ == '__main__':
    main()
