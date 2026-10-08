"""Deprecated tool names, kept for one release so existing prompts keep working.

Each one delegates to its replacement or keeps its old behavior. They register
with one-line descriptions to keep tools/list small. Set
GTM_MCP_LEGACY_TOOLS=0 to hide them; they're removed in the next release.
"""
import os

from gtm_mcp import read_tools, write_tools
from gtm_mcp.helpers import (
    _resolve_workspace_parent, _run, _validate_ids, get_gtm_client, gtm_tool,
)

ENABLED = os.getenv("GTM_MCP_LEGACY_TOOLS", "1") != "0"


def _alias(fn):
    """Register ``fn`` as a tool only while legacy tools are enabled."""
    return gtm_tool(f"{fn.__name__} failed")(fn) if ENABLED else fn


@_alias
async def test_gtm_connection(account_id: str) -> dict:
    """Deprecated: use ``list_gtm_containers``."""
    return await read_tools.list_gtm_containers(account_id)


@_alias
async def get_gtm_live_version(account_id: str, container_id: str) -> dict:
    """Deprecated: use ``get_gtm_container_version`` (version_id defaults to "live")."""
    return await read_tools.get_gtm_container_version(account_id, container_id, "live")


@_alias
async def create_js_variable(
    account_id: str, container_id: str, variable_name: str, javascript: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``create_gtm_variable`` with ``javascript``."""
    return await write_tools.create_gtm_variable(
        account_id, container_id, variable_name, javascript=javascript, workspace_id=workspace_id)


@_alias
async def create_datalayer_variable(
    account_id: str, container_id: str, variable_name: str, datalayer_key: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``create_gtm_variable`` with ``datalayer_key``."""
    return await write_tools.create_gtm_variable(
        account_id, container_id, variable_name, datalayer_key=datalayer_key,
        workspace_id=workspace_id)


@_alias
async def update_tag_consent_settings(
    account_id: str, container_id: str, tag_id: str, consent_status: str,
    consent_types: list | None = None, workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tag`` with ``consent_status`` / ``consent_types``."""
    return await write_tools.update_tag(
        account_id, container_id, tag_id, consent_status=consent_status,
        consent_types=consent_types, workspace_id=workspace_id)


@_alias
async def set_firing_triggers_on_tags_batch(
    account_id: str, container_id: str, tag_ids: list, trigger_ids: list,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tags_triggers_batch`` with action="set", kind="firing"."""
    return await write_tools.update_tags_triggers_batch(
        account_id, container_id, tag_ids, "set", trigger_ids, "firing", workspace_id)


@_alias
async def add_firing_trigger_to_tags_batch(
    account_id: str, container_id: str, tag_ids: list, trigger_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tags_triggers_batch`` with action="add", kind="firing"."""
    return await write_tools.update_tags_triggers_batch(
        account_id, container_id, tag_ids, "add", [trigger_id], "firing", workspace_id)


@_alias
async def add_blocking_trigger_to_tags_batch(
    account_id: str, container_id: str, tag_ids: list, trigger_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tags_triggers_batch`` with action="add", kind="blocking"."""
    return await write_tools.update_tags_triggers_batch(
        account_id, container_id, tag_ids, "add", [trigger_id], "blocking", workspace_id)


@_alias
async def remove_firing_trigger_from_tags_batch(
    account_id: str, container_id: str, tag_ids: list, trigger_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tags_triggers_batch`` with action="remove", kind="firing"."""
    return await write_tools.update_tags_triggers_batch(
        account_id, container_id, tag_ids, "remove", [trigger_id], "firing", workspace_id)


@_alias
async def remove_blocking_trigger_from_tags_batch(
    account_id: str, container_id: str, tag_ids: list, trigger_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tags_triggers_batch`` with action="remove", kind="blocking"."""
    return await write_tools.update_tags_triggers_batch(
        account_id, container_id, tag_ids, "remove", [trigger_id], "blocking", workspace_id)


@_alias
async def update_tag_html(
    account_id: str,
    container_id: str,
    tag_id: str,
    html: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tag_parameters`` with the ``html`` parameter. Custom HTML tags only."""
    error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    workspace_id, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    path = f"{ws_parent}/tags/{tag_id}"

    tag = await _run(client.service.accounts().containers().workspaces().tags().get(path=path))

    if tag.get("type") != "html":
        return {
            "status": "error",
            "message": f"Tag '{tag.get('name')}' is type '{tag.get('type')}', not 'html'. Only Custom HTML tags can be updated with this tool.",
        }

    params = tag.get("parameter", [])
    html_param = next((p for p in params if p.get("key") == "html"), None)
    if html_param is None:
        return {
            "status": "error",
            "message": f"Tag '{tag.get('name')}' has no 'html' parameter.",
        }

    html_param["value"] = html

    updated = await _run(
        client.service.accounts().containers().workspaces().tags().update(
            path=path, body=tag, fingerprint=tag.get("fingerprint")
        )
    )

    return {
        "status": "success",
        "message": f"HTML updated for tag '{updated.get('name')}'",
        "tag_id": tag_id,
        "tag_name": updated.get("name"),
    }


async def _set_tag_paused(client, ws_parent: str, tag_id: str, paused: bool) -> dict:
    """Toggle a tag's `paused` flag, preserving every other field.

    No-op (returns status="noop") if the tag is already in the requested state.
    Uses fingerprint for optimistic concurrency on the update.
    """
    path = f"{ws_parent}/tags/{tag_id}"
    tag = await _run(
        client.service.accounts().containers().workspaces().tags().get(path=path)
    )

    current = bool(tag.get("paused", False))
    if current == paused:
        return {
            "status": "noop",
            "message": f"Tag '{tag.get('name')}' already {'paused' if paused else 'unpaused'}",
            "tag_id": tag_id,
            "tag_name": tag.get("name"),
            "paused": current,
        }

    tag["paused"] = paused
    updated = await _run(
        client.service.accounts().containers().workspaces().tags().update(
            path=path, body=tag, fingerprint=tag.get("fingerprint"),
        )
    )
    return {
        "status": "success",
        "message": f"Tag '{updated.get('name')}' {'paused' if paused else 'unpaused'}",
        "tag_id": tag_id,
        "tag_name": updated.get("name"),
        "paused": paused,
    }


@_alias
async def pause_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tag`` with ``paused=True``. Returns status 'noop' if already paused."""
    error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    return await _set_tag_paused(client, ws_parent, tag_id, paused=True)


@_alias
async def unpause_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Deprecated: use ``update_tag`` with ``paused=False``. Returns status 'noop' if already unpaused."""
    error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    return await _set_tag_paused(client, ws_parent, tag_id, paused=False)
