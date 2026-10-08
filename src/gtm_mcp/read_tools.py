"""Read-only MCP tools: discovery, tags/triggers/variables, version history.

Also holds delete_gtm_variable for historical reasons. Tools register on the
shared ``mcp`` instance from ``gtm_mcp.helpers``.
"""
import asyncio

from gtm_mcp.helpers import (
    gtm_tool, get_gtm_client, _run,
    _validate_ids, _paginated_list, _resolve_workspace_parent,
    _fingerprint_to_iso, _summarize_version, _diff_versions,
    _ENTITY_ID_FIELDS, _find_references,
)


# ---------------------------------------------------------------------------
# Read / query tools
# ---------------------------------------------------------------------------

@gtm_tool("Failed to list containers")
async def list_gtm_containers(account_id: str) -> dict:
    """List all GTM containers in an account.

    Calls tagmanager.accounts.containers.list. Returns container names, IDs,
    public IDs, and usage contexts. Use this to discover container IDs needed
    by most other tools.

    Args:
        account_id: GTM Account ID (numeric string)
    """
    error = _validate_ids(account_id=account_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    containers = await _paginated_list(
        lambda **kw: client.service.accounts().containers().list(parent=f"accounts/{account_id}", **kw),
        'container'
    )

    return {
        "status": "success",
        "account_id": account_id,
        "total_containers": len(containers),
        "containers": containers
    }

@gtm_tool("Failed to list accounts")
async def list_gtm_accounts() -> dict:
    """List all GTM accounts the authenticated user has access to.

    Calls tagmanager.accounts.list. Returns each account's name, ID, and path.
    This is typically the first discovery call — use the returned account IDs
    with list_gtm_containers to find containers.
    """
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


@gtm_tool("Failed to list workspaces")
async def list_gtm_workspaces(account_id: str, container_id: str) -> dict:
    """List all workspaces in a GTM container.

    Calls tagmanager.accounts.containers.workspaces.list.
    Returns each workspace's name, ID, and description. The workspace ID is
    required by most tools that modify container contents.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
    """
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

@gtm_tool("Failed to list variables")
async def list_gtm_variables(account_id: str, container_id: str, workspace_id: str | None = None) -> dict:
    """List all variables in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.variables.list.
    Returns each variable's name, type, and ID.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
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

@gtm_tool("Failed to list tags")
async def list_gtm_tags(account_id: str, container_id: str, workspace_id: str | None = None) -> dict:
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


@gtm_tool("Failed to get tag")
async def get_gtm_tag(account_id: str, container_id: str, tag_id: str, workspace_id: str | None = None) -> dict:
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


@gtm_tool("Failed to get variable")
async def get_gtm_variable(
    account_id: str,
    container_id: str,
    variable_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Get full details of a specific GTM variable, including its parameters.

    Calls tagmanager.accounts.containers.workspaces.variables.get.
    For JS Macro (jsm) variables, the JavaScript source is in the parameter
    list under key="javascript". For Data Layer Variables (v), the dataLayer
    key is under key="name".

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variable_id: The variable ID to retrieve
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(
        account_id=account_id, container_id=container_id, variable_id=variable_id
    )
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    workspace_id, ws_parent = await _resolve_workspace_parent(
        client, account_id, container_id, workspace_id
    )
    path = f"{ws_parent}/variables/{variable_id}"

    variable = await _run(
        client.service.accounts().containers().workspaces().variables().get(path=path)
    )

    return {"status": "success", "variable": variable}


@gtm_tool("Failed to list triggers")
async def list_gtm_triggers(account_id: str, container_id: str, workspace_id: str | None = None) -> dict:
    """List all triggers in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.triggers.list.
    Returns each trigger's name, type, ID, filter conditions, and custom event filters.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
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


@gtm_tool("Failed to get trigger")
async def get_gtm_trigger(
    account_id: str, container_id: str, trigger_id: str, workspace_id: str | None = None,
) -> dict:
    """Get full details of one trigger: type, filters, auto-event settings, parameters.

    Built-in triggers such as All Pages (ID 2147479553) aren't workspace
    resources and return 404; ``find_gtm_references`` still works for them.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_id: The trigger ID to retrieve
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    trigger = await _run(client.service.accounts().containers().workspaces().triggers().get(
        path=f"{ws_parent}/triggers/{trigger_id}"))
    return {"status": "success", "trigger": trigger}


_REFERENCE_COLLECTIONS = {"tag": "tags", "trigger": "triggers", "variable": "variables"}


@gtm_tool("Failed to find references")
async def find_gtm_references(
    account_id: str,
    container_id: str,
    kind: str,
    entity_id: str,
    workspace_id: str | None = None,
) -> dict:
    """Find everything in a workspace that uses a trigger, variable, or tag.

    Run before deleting or renaming — GTM's API doesn't stop you from leaving
    dangling references, and renaming a variable through the API does NOT
    rewrite ``{{Old Name}}`` where it's used.

    - ``kind="trigger"``: tags firing on or blocked by it; trigger groups containing it.
    - ``kind="variable"``: every ``{{Name}}`` use in tags, triggers, and other variables
      (custom JS, HTML, filters, parameters), with the field path.
    - ``kind="tag"``: tags that sequence it (setup / teardown).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        kind: "trigger", "variable", or "tag"
        entity_id: ID of the entity to look up
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    if kind not in _REFERENCE_COLLECTIONS:
        return {"status": "error", "message": f"kind must be one of {list(_REFERENCE_COLLECTIONS)}, got '{kind}'"}
    error = _validate_ids(account_id=account_id, container_id=container_id, entity_id=entity_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    _, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    ws = client.service.accounts().containers().workspaces()

    def lister(collection):
        return lambda **kw: getattr(ws, collection)().list(parent=parent, **kw)

    tags, triggers, variables = await asyncio.gather(
        _paginated_list(lister("tags"), "tag"),
        _paginated_list(lister("triggers"), "trigger"),
        _paginated_list(lister("variables"), "variable"),
    )
    pool = {"tag": tags, "trigger": triggers, "variable": variables}[kind]
    id_field = _ENTITY_ID_FIELDS[kind]
    target = next((e for e in pool if e.get(id_field) == entity_id), None)
    if target is None:
        if kind != "trigger":
            return {"status": "error", "message": f"{kind.capitalize()} {entity_id} not found in this workspace."}
        # Built-in triggers (All Pages = 2147479553, …) aren't workspace resources.
        target = {"triggerId": entity_id, "name": "(built-in trigger)"}
    refs = _find_references(kind, target, tags, triggers, variables)
    return {
        "status": "success",
        "target": {"kind": kind, "id": target.get(_ENTITY_ID_FIELDS[kind]), "name": target.get("name")},
        "total_references": len(refs),
        "references": refs,
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


@gtm_tool("Failed to list container versions")
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


@gtm_tool("Failed to get container version")
async def get_gtm_container_version(account_id: str, container_id: str, version_id: str = "live") -> dict:
    """Get a summarized snapshot of a specific GTM container version.

    Calls tagmanager.accounts.containers.versions.get (or versions.live when
    version_id is "live"). Returns identity fields, entity counts, and slim
    tag/trigger/variable listings — never the raw resource, which exceeds 200KB
    on large containers. fingerprint_datetime (ISO 8601 UTC, derived from the
    version's fingerprint) is effectively the version's creation time.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        version_id: Container version ID, or "live" (default) for the published version
    """
    return await _get_version_summary(account_id, container_id, version_id)


@gtm_tool("Failed to diff container versions")
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
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    for name, version_id in (("from_version_id", from_version_id), ("to_version_id", to_version_id)):
        error = _validate_version_id(name, version_id)
        if error:
            return {"status": "error", "message": error}

    client = get_gtm_client()
    from_version, to_version = await asyncio.gather(
        _fetch_version(client, account_id, container_id, from_version_id),
        _fetch_version(client, account_id, container_id, to_version_id),
    )

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


@gtm_tool("Failed to delete variable")
async def delete_gtm_variable(account_id: str, container_id: str, variable_id: str, workspace_id: str | None = None) -> dict:
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
