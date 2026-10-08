"""Version and workspace lifecycle: draft versions, publish/rollback, workspaces, revert.

Tools register on the shared ``mcp`` instance from ``gtm_mcp.helpers``.
"""
from gtm_mcp.helpers import (
    _forget_workspace, _resolve_workspace_parent, _run, _validate_ids, get_gtm_client, gtm_tool,
)

# entity kind → (collection accessor, response key, id field)
_REVERTIBLE = {
    "tag": ("tags", "tag", "tagId"),
    "trigger": ("triggers", "trigger", "triggerId"),
    "variable": ("variables", "variable", "variableId"),
}


def _version_brief(version: dict) -> dict:
    return {
        "version_id": version.get("containerVersionId"),
        "name": version.get("name"),
        "path": version.get("path"),
        "tagManagerUrl": version.get("tagManagerUrl"),
    }


def _change_brief(change: dict) -> dict:
    """Flatten a workspaceChange / mergeConflict entity into {kind, id, name, status}."""
    for kind, (_, key, id_field) in _REVERTIBLE.items():
        if key in change:
            entity = change[key]
            return {"kind": kind, "id": entity.get(id_field), "name": entity.get("name"),
                    "status": change.get("changeStatus")}
    other = next((k for k in change if k != "changeStatus"), None)
    entity = change.get(other, {}) if other else {}
    return {"kind": other, "name": entity.get("name"), "status": change.get("changeStatus")}


async def _create_version(client, account_id, container_id, workspace_id, name, notes):
    """create_version from a workspace → (workspace_id, version, response).

    ``version`` is None when GTM refused (compiler errors / merge conflicts);
    the response then says why. Clears the workspace cache either way: a
    version from the Default Workspace replaces it.
    """
    ws_id, ws_path = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    created = await _run(client.service.accounts().containers().workspaces().create_version(
        path=ws_path, body={"name": name, "notes": notes}))
    _forget_workspace(account_id, container_id)
    return ws_id, created.get("containerVersion"), created


def _no_version_error(ws_id, created):
    problems = {k: created[k] for k in ("compilerError", "syncStatus") if created.get(k)}
    return {"status": "error",
            "message": f"Workspace {ws_id} did not produce a version: {problems or created}"}


@gtm_tool("Failed to create version")
async def create_gtm_version(
    account_id: str,
    container_id: str,
    version_name: str,
    version_notes: str = "",
    workspace_id: str | None = None,
) -> dict:
    """Create a container version from a workspace WITHOUT publishing it.

    Use this to snapshot changes for review, then ``publish_gtm_version`` when
    approved (``publish_gtm_container`` does both steps at once). GTM refuses
    to create a version when the workspace has compiler errors or unresolved
    merge conflicts; those are returned as the error. Creating a version from
    the Default Workspace replaces it with a new, empty one (new ID).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        version_name: Name for the new version
        version_notes: Notes describing the changes
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    ws_id, version, created = await _create_version(
        client, account_id, container_id, workspace_id, version_name, version_notes)
    if not version:
        return _no_version_error(ws_id, created)
    return {
        "status": "success",
        "message": f"Version {version.get('containerVersionId')} created (not published)",
        **_version_brief(version),
        "new_workspace_path": created.get("newWorkspacePath"),
    }


@gtm_tool("Failed to publish container")
async def publish_gtm_container(
    account_id: str,
    container_id: str,
    version_name: str,
    version_notes: str = "Published via MCP",
    workspace_id: str | None = None,
) -> dict:
    """Create a version from a workspace and publish it — all its changes go live.

    Same as ``create_gtm_version`` followed by ``publish_gtm_version``; use those
    two to review the version before it goes live. Check
    ``get_gtm_workspace_status`` first to see exactly what will ship.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        version_name: Name for the new version
        version_notes: Notes describing the changes
        workspace_id: GTM Workspace ID to publish from (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    ws_id, version, created = await _create_version(
        client, account_id, container_id, workspace_id, version_name, version_notes)
    if not version or not version.get("path"):
        return _no_version_error(ws_id, created)
    result = await _run(client.service.accounts().containers().versions().publish(path=version["path"]))

    published = result.get("containerVersion", {})
    return {
        "status": "success",
        "message": f"Container {container_id} published successfully",
        "version_name": version_name,
        "version_notes": version_notes,
        "version_id": published.get("containerVersionId"),
        "path": published.get("path"),
    }


@gtm_tool("Failed to publish version")
async def publish_gtm_version(account_id: str, container_id: str, version_id: str) -> dict:
    """Publish an existing container version — the way to roll back.

    Publishing an older version makes it live immediately. It does NOT touch
    workspaces: changes still sitting in the Default Workspace will go live
    again with the next publish from it. Use ``list_gtm_container_versions`` to
    pick the version and ``diff_gtm_container_versions`` (version → "live") to
    see exactly what the rollback changes before running it.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        version_id: Numeric container version ID to make live
    """
    error = _validate_ids(account_id=account_id, container_id=container_id, version_id=version_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    path = f"accounts/{account_id}/containers/{container_id}/versions/{version_id}"
    result = await _run(client.service.accounts().containers().versions().publish(path=path))
    if result.get("compilerError"):
        return {"status": "error", "message": f"Version {version_id} has compiler errors; not published."}
    return {
        "status": "success",
        "message": f"Version {version_id} is now live on container {container_id}",
        **_version_brief(result.get("containerVersion", {})),
    }


@gtm_tool("Failed to create workspace")
async def create_gtm_workspace(
    account_id: str, container_id: str, name: str, description: str = "",
) -> dict:
    """Create a new workspace, branched from the latest container version.

    A separate workspace keeps one person's draft out of everyone else's — pass
    its ID as ``workspace_id`` to the other tools. GTM limits a container to 3
    workspaces on the free tier.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        name: Workspace name
        description: Optional description
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    if not name or not name.strip():
        return {"status": "error", "message": "name must be a non-empty string"}

    client = get_gtm_client()
    ws = await _run(client.service.accounts().containers().workspaces().create(
        parent=f"accounts/{account_id}/containers/{container_id}",
        body={"name": name, "description": description}))
    _forget_workspace(account_id, container_id)
    return {
        "status": "success",
        "message": f"Workspace '{ws.get('name')}' created",
        "workspace_id": ws.get("workspaceId"),
        "name": ws.get("name"),
        "path": ws.get("path"),
    }


@gtm_tool("Failed to get workspace status")
async def get_gtm_workspace_status(
    account_id: str, container_id: str, workspace_id: str | None = None,
) -> dict:
    """List a workspace's pending changes and merge conflicts.

    Shows what would ship with the next version from this workspace (each
    added/updated/deleted tag, trigger, variable…) and any conflicts with the
    latest container version. Check this before ``create_gtm_version`` /
    ``publish_gtm_container``; resolve conflicts with ``sync_gtm_workspace``.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    ws_id, ws_path = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    status = await _run(client.service.accounts().containers().workspaces().getStatus(path=ws_path))
    changes = [_change_brief(c) for c in status.get("workspaceChange", [])]
    conflicts = [
        {"workspace": _change_brief(c.get("entityInWorkspace", {})),
         "base_version": _change_brief(c.get("entityInBaseVersion", {}))}
        for c in status.get("mergeConflict", [])
    ]
    return {
        "status": "success",
        "workspace_id": ws_id,
        "total_changes": len(changes),
        "changes": changes,
        "merge_conflicts": conflicts,
    }


@gtm_tool("Failed to sync workspace")
async def sync_gtm_workspace(
    account_id: str, container_id: str, workspace_id: str | None = None,
) -> dict:
    """Bring a workspace up to date with the latest container version.

    Needed after someone else publishes: GTM won't create a version from a
    stale workspace. Non-conflicting changes merge automatically; conflicts are
    returned and must be fixed (edit the entity, or ``revert_gtm_entity``)
    before publishing.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    ws_id, ws_path = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    result = await _run(client.service.accounts().containers().workspaces().sync(path=ws_path))
    sync = result.get("syncStatus", {})
    if sync.get("syncError"):
        return {"status": "error", "message": f"Sync of workspace {ws_id} failed: {result}"}
    conflicts = [
        {"workspace": _change_brief(c.get("entityInWorkspace", {})),
         "base_version": _change_brief(c.get("entityInBaseVersion", {}))}
        for c in result.get("mergeConflict", [])
    ]
    return {
        "status": "partial" if conflicts else "success",
        "message": (f"Workspace {ws_id} synced with {len(conflicts)} merge conflict(s) to resolve"
                    if conflicts else f"Workspace {ws_id} is up to date"),
        "workspace_id": ws_id,
        "merge_conflicts": conflicts,
    }


@gtm_tool("Failed to revert")
async def revert_gtm_entity(
    account_id: str,
    container_id: str,
    kind: str,
    entity_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Undo a workspace's changes to one tag, trigger, or variable.

    Restores the entity to how it is in the latest container version: edits
    are discarded, an entity created in this workspace is removed, a deleted
    one comes back. Only affects the workspace — nothing live changes.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        kind: "tag", "trigger", or "variable"
        entity_id: ID of the entity to revert
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    if kind not in _REVERTIBLE:
        return {"status": "error", "message": f"kind must be one of {list(_REVERTIBLE)}, got '{kind}'"}
    error = _validate_ids(account_id=account_id, container_id=container_id, entity_id=entity_id)
    if error:
        return {"status": "error", "message": error}

    collection, key, _ = _REVERTIBLE[kind]
    client = get_gtm_client()
    ws_id, ws_path = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    resource = getattr(client.service.accounts().containers().workspaces(), collection)()
    result = await _run(resource.revert(path=f"{ws_path}/{collection}/{entity_id}"))
    entity = result.get(key)
    return {
        "status": "success",
        "message": (f"{kind.capitalize()} {entity_id} reverted to the latest version"
                    if entity else f"{kind.capitalize()} {entity_id} was new in this workspace and is removed"),
        "kind": kind,
        "entity_id": entity_id,
        "workspace_id": ws_id,
        "name": (entity or {}).get("name"),
    }
