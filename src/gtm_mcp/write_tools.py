"""Write MCP tools: create/update/delete tags, triggers, variables; publish.

Tools register on the shared ``mcp`` instance from ``gtm_mcp.helpers``.
"""
import copy

from gtm_mcp.helpers import (
    gtm_tool, get_gtm_client, _run, _forget_workspace,
    MAX_BATCH_SIZE,
    _create_datalayer_var,
    _validate_consent_params, _build_consent_settings,
    _validate_firing_option,
    _validate_ids, _resolve_workspace_parent,
    _batch_update_tags,
    _datalayer_parameters,
    _modify_tag_triggers_batch,
    _upsert_parameters,
    _validate_trigger_filters,
    _filter_tuples_to_conditions,
)


# ---------------------------------------------------------------------------
# Tag creation
# ---------------------------------------------------------------------------

@gtm_tool("Failed to create tag")
async def create_tag(
    account_id: str,
    container_id: str,
    name: str,
    tag_type: str,
    parameter: list = None,
    firing_trigger_ids: list = None,
    blocking_trigger_ids: list = None,
    consent_status: str = None,
    consent_types: list = None,
    notes: str = None,
    paused: bool = False,
    tag_firing_option: str = None,
    workspace_id: str | None = None,
) -> dict:
    """Create any tag in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.tags.create to create a tag
    of any type (GA4, Custom HTML, Facebook Pixel, Google Ads, etc.).

    The ``parameter`` list uses GTM's native format — each item is a dict with
    ``key``, ``value``, and ``type`` (usually ``"template"``). Use ``get_gtm_tag``
    on an existing tag to see the parameter format for a given tag type.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        name: Display name for the tag in GTM
        tag_type: GTM tag type identifier (e.g. "gtagjs", "html", "ua", "fbpixel", "gclidw")
        parameter: List of parameter dicts in GTM format: [{"key": "...", "value": "...", "type": "template"}, ...]
        firing_trigger_ids: List of trigger ID strings that cause this tag to fire
        blocking_trigger_ids: List of trigger ID strings that prevent this tag from firing
        consent_status: Consent requirement — "notSet", "notNeeded", or "needed"
        consent_types: List of consent types required when consent_status is "needed"
                       (e.g. ["ad_storage", "analytics_storage"])
        notes: Optional user notes describing the tag's purpose
        paused: Whether the tag should be created in a paused state (default False)
        tag_firing_option: Firing option — "unlimited", "oncePerEvent", or "oncePerLoad"
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}

    if consent_status is not None:
        error = _validate_consent_params(consent_status, consent_types)
        if error:
            return {"status": "error", "message": error}

    client = get_gtm_client()
    workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

    tag_body = {"name": name, "type": tag_type}

    if parameter:
        tag_body["parameter"] = parameter
    if firing_trigger_ids:
        tag_body["firingTriggerId"] = firing_trigger_ids
    if blocking_trigger_ids:
        tag_body["blockingTriggerId"] = blocking_trigger_ids
    if consent_status is not None:
        tag_body["consentSettings"] = _build_consent_settings(consent_status, consent_types)
    if notes:
        tag_body["notes"] = notes
    if paused:
        tag_body["paused"] = True
    if tag_firing_option:
        tag_body["tagFiringOption"] = tag_firing_option

    result = await _run(
        client.service.accounts().containers().workspaces().tags().create(
            parent=parent, body=tag_body
        )
    )

    return {
        "status": "success",
        "message": f"Tag '{name}' created successfully",
        "tag_id": result.get("tagId"),
        "tag_name": name,
        "tag_type": tag_type,
        "path": result.get("path"),
    }


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

@gtm_tool("Failed to publish container")
async def publish_gtm_container(account_id: str, container_id: str, version_name: str, version_notes: str = "Published via MCP", workspace_id: str | None = None) -> dict:
    """Publish GTM container version. Creates a version from the workspace and publishes it.

    Two-step process: first creates a version from the workspace
    (tagmanager.accounts.containers.workspaces.create_version), then publishes it
    (tagmanager.accounts.containers.versions.publish). This makes all workspace
    changes live.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        version_name: Name for the new version
        version_notes: Optional notes describing the version changes
        workspace_id: GTM Workspace ID to publish from (auto-detected if omitted). Use list_gtm_workspaces to find the correct workspace.
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    workspace_id, ws_path = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

    created = await _run(client.service.accounts().containers().workspaces().create_version(
        path=ws_path, body={"name": version_name, "notes": version_notes}))
    version_path = created.get("containerVersion", {}).get("path")
    if not version_path:
        # No version means GTM refused: compiler errors or an unresolved merge conflict.
        problems = {k: created[k] for k in ("compilerError", "syncStatus") if created.get(k)}
        return {"status": "error",
                "message": f"Workspace {workspace_id} did not produce a version: {problems or created}"}
    result = await _run(client.service.accounts().containers().versions().publish(path=version_path))
    _forget_workspace(account_id, container_id)

    version = result.get("containerVersion", {})
    return {
        "status": "success",
        "message": f"Container {container_id} published successfully",
        "version_name": version_name,
        "version_notes": version_notes,
        "version_id": version.get("containerVersionId"),
        "path": version.get("path"),
    }


# ---------------------------------------------------------------------------
# Data Layer Variables
# ---------------------------------------------------------------------------

@gtm_tool("Failed to create Data Layer Variables")
async def create_datalayer_variables_batch(account_id: str, container_id: str, variables: list, workspace_id: str | None = None) -> dict:
    """Create multiple Data Layer Variables in a GTM workspace at once.

    Iterates over a list of variable definitions and creates each as a type 'v'
    (Data Layer Variable) using dataLayer version 2. Reports per-variable
    success/failure.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variables: List of dicts with 'name' (display name) and 'key' (dataLayer key).
                   Example: [{"name": "DLV - fs_order_id", "key": "fs_order_id"}, ...]
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    if len(variables) > MAX_BATCH_SIZE:
        return {"status": "error", "message": f"Batch size {len(variables)} exceeds limit of {MAX_BATCH_SIZE}."}
    for i, var in enumerate(variables):
        if not isinstance(var, dict) or not var.get('name') or not var.get('key'):
            return {"status": "error", "message": f"Variable at index {i} must have non-empty 'name' and 'key' strings."}

    client = get_gtm_client()
    workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    results = {"created": [], "failed": []}

    for var in variables:
        try:
            result = await _create_datalayer_var(client, parent, var['name'], var['key'])
            results["created"].append(result)
        except Exception as e:
            results["failed"].append({"name": var['name'], "key": var['key'], "error": str(e)})

    n_created, n_failed = len(results["created"]), len(results["failed"])
    results["status"] = "error" if n_failed and not n_created else "partial" if n_failed else "success"
    results["summary"] = f"Created {n_created}/{len(variables)} variables"
    return results


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

_VALID_TRIGGER_TYPES = {
    "pageview", "domReady", "windowLoaded", "customEvent", "click", "linkClick",
    "formSubmission", "timer", "elementVisibility", "historyChange", "scrollDepth",
    "youTubeVideo", "init", "consentInit", "pageviewGtm", "serverPageview",
    "triggerGroup",
}


@gtm_tool("Failed to create trigger")
async def create_trigger(
    account_id: str,
    container_id: str,
    trigger_name: str,
    event_name: str | None = None,
    trigger_type: str = "customEvent",
    filters: list[dict] | None = None,
    workspace_id: str | None = None
) -> dict:
    """Create a trigger in a GTM workspace.

    Supports the common GTM trigger types. The most common are:

    - ``customEvent`` (default) — fires on ``dataLayer.push({'event': <name>})``.
      Requires ``event_name``. Example: set ``event_name="consent_update"`` to
      fire on ``dataLayer.push({'event': 'consent_update'})``.
    - ``pageview`` — fires when gtm.js runs (first paint-ish).
    - ``init`` — Init-All-Pages; fires before the standard pageview trigger.
    - ``consentInit`` — fires before ``init``, intended for consent defaults.
    - ``domReady`` / ``windowLoaded`` — standard page lifecycle triggers.
    - ``click`` / ``linkClick`` / ``formSubmission`` / ``scrollDepth`` /
      ``elementVisibility`` / ``timer`` / ``historyChange`` / ``youTubeVideo`` /
      ``triggerGroup`` / ``pageviewGtm`` / ``serverPageview``.

    ``event_name`` is only used when ``trigger_type == "customEvent"`` (it is
    ignored for other types). For ``customEvent`` triggers without ``event_name``
    you get a validation error.

    Optional ``filters`` adds AND-ed conditions to the trigger (equivalent to
    the GTM UI "Fire on Some ..." conditions). Each item is a GTM Condition
    dict with ``type`` and ``parameter``, e.g.
    ``{"type": "equals", "parameter": [{"key": "arg0", "value": "{{utm_source}}", "type": "template"},
    {"key": "arg1", "value": "google_yt_el", "type": "template"}]}``.

    Note: the GTM REST Condition schema has no ``negate`` flag. To express
    "does not equal X", use ``type: "matchRegex"`` with a negative lookahead
    pattern such as ``^(?!X$).*$``, or invert the intent (use the trigger as
    a firing filter rather than an exception).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_name: Display name for the trigger in GTM (e.g., "CE - consent_update")
        event_name: The custom event name to match — required when trigger_type is "customEvent"
        trigger_type: GTM trigger type (default "customEvent"). See list above.
        filters: Optional list of GTM Condition dicts to AND with the trigger's base match
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    if trigger_type not in _VALID_TRIGGER_TYPES:
        return {"status": "error", "message": f"Unsupported trigger_type '{trigger_type}'. Valid: {sorted(_VALID_TRIGGER_TYPES)}"}
    if trigger_type == "customEvent" and not event_name:
        return {"status": "error", "message": "event_name is required when trigger_type is 'customEvent'"}
    if filters is not None:
        filter_error = _validate_trigger_filters(filters)
        if filter_error:
            return {"status": "error", "message": filter_error}

    client = get_gtm_client()
    workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

    trigger_body: dict = {
        'name': trigger_name,
        'type': trigger_type,
    }
    if trigger_type == "customEvent":
        trigger_body['customEventFilter'] = [
            {
                'type': 'equals',
                'parameter': [
                    {'key': 'arg0', 'value': '{{_event}}', 'type': 'template'},
                    {'key': 'arg1', 'value': event_name, 'type': 'template'}
                ]
            }
        ]
    if filters:
        trigger_body['filter'] = filters

    result = await _run(client.service.accounts().containers().workspaces().triggers().create(
        parent=parent,
        body=trigger_body
    ))

    return {
        "status": "success",
        "message": f"{trigger_type} trigger '{trigger_name}' created successfully",
        "trigger_id": result.get('triggerId'),
        "trigger_name": trigger_name,
        "trigger_type": trigger_type,
        "event_name": event_name if trigger_type == "customEvent" else None,
        "filters": filters or [],
        "path": result.get('path')
    }


# ---------------------------------------------------------------------------
# Tag deletion
# ---------------------------------------------------------------------------

@gtm_tool("Failed to delete tag")
async def delete_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str | None = None
) -> dict:
    """Delete a tag from a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.tags.delete. Permanent
    within the workspace — publish to make it live, or discard workspace
    changes to undo.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    _, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    path = f"{parent}/tags/{tag_id}"

    await _run(client.service.accounts().containers().workspaces().tags().delete(path=path))

    return {
        "status": "success",
        "message": f"Tag '{tag_id}' deleted",
        "tag_id": tag_id,
    }


# ---------------------------------------------------------------------------
# Trigger deletion
# ---------------------------------------------------------------------------

@gtm_tool("Failed to delete trigger")
async def delete_trigger(
    account_id: str,
    container_id: str,
    trigger_id: str,
    workspace_id: str | None = None
) -> dict:
    """Delete a trigger from a GTM workspace.

    Removes the trigger resource entirely. Tags that reference this trigger via
    ``firingTriggerId`` or ``blockingTriggerId`` will have dangling references
    after deletion — detach it first with ``update_tags_triggers_batch``
    (``action="remove"``, ``kind="firing"`` or ``"blocking"``).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_id: The trigger ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    _, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    path = f"{parent}/triggers/{trigger_id}"

    await _run(client.service.accounts().containers().workspaces().triggers().delete(path=path))

    return {
        "status": "success",
        "message": f"Trigger '{trigger_id}' deleted",
        "trigger_id": trigger_id,
    }


# Top-level trigger fields that update_trigger_parameters will overwrite.
# Anything outside this set is rejected client-side to catch typos before
# the API does.
_UPDATABLE_TRIGGER_FIELDS = frozenset({
    "name",
    "filter",
    "customEventFilter",
    "autoEventFilter",
    "interval",
    "limit",
    "checkValidation",
    "waitForTags",
})

_TRIGGER_FILTER_KEYS = ("filter", "customEventFilter", "autoEventFilter")


def _http_status(exc) -> int | None:
    """Extract HTTP status from a googleapiclient HttpError, if present."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


async def _update_trigger_parameters_impl(
    account_id: str,
    container_id: str,
    trigger_id: str,
    fields: dict,
    workspace_id: str | None = None,
) -> dict:
    """Shared implementation for update_trigger_parameters / update_trigger_filter."""
    error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
    if error:
        return {"status": "error", "message": error}
    if not isinstance(fields, dict) or not fields:
        return {"status": "error", "message": "fields must be a non-empty dict."}

    unknown = sorted(set(fields) - _UPDATABLE_TRIGGER_FIELDS)
    if unknown:
        return {
            "status": "error",
            "message": f"Unsupported field(s) {unknown}. Allowed: {sorted(_UPDATABLE_TRIGGER_FIELDS)}",
        }

    if "name" in fields:
        if fields["name"] is None:
            return {"status": "error", "message": "fields['name'] cannot be None — name is required on GTM triggers. Omit the key to leave it unchanged."}
        if not isinstance(fields["name"], str) or not fields["name"].strip():
            return {"status": "error", "message": "fields['name'] must be a non-empty string."}

    for key in _TRIGGER_FILTER_KEYS:
        if key in fields and fields[key] is not None:
            err = _validate_trigger_filters(fields[key])
            if err:
                return {"status": "error", "message": f"fields['{key}']: {err}"}

    for key in ("interval", "limit", "checkValidation", "waitForTags"):
        if key in fields and fields[key] is not None and not isinstance(fields[key], dict):
            return {
                "status": "error",
                "message": f"fields['{key}'] must be a GTM Parameter dict (e.g. {{'type': 'integer', 'key': '{key}', 'value': '...'}})",
            }

    client = get_gtm_client()
    resolved_ws, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    path = f"{parent}/triggers/{trigger_id}"

    try:
        trigger = await _run(client.service.accounts().containers().workspaces().triggers().get(path=path))
    except Exception as e:
        if _http_status(e) == 404:
            return {
                "status": "error",
                "message": f"Trigger '{trigger_id}' not found in workspace '{resolved_ws}' of container '{container_id}'.",
            }
        raise

    updated_keys = []
    for key, value in fields.items():
        if value is None:
            if key in trigger:
                del trigger[key]
                updated_keys.append(key)
        else:
            trigger[key] = value
            updated_keys.append(key)

    try:
        updated = await _run(
            client.service.accounts().containers().workspaces().triggers().update(
                path=path, body=trigger, fingerprint=trigger.get("fingerprint")
            )
        )
    except Exception as e:
        if _http_status(e) == 409:
            return {
                "status": "error",
                "message": (
                    f"Fingerprint conflict on trigger '{trigger_id}' in workspace "
                    f"'{resolved_ws}' — the trigger changed since it was fetched. "
                    "Re-fetch and retry."
                ),
            }
        raise

    return {
        "status": "success",
        "message": f"Updated {len(updated_keys)} field(s) on trigger '{updated.get('name')}'",
        "trigger_id": trigger_id,
        "trigger_name": updated.get("name"),
        "trigger_type": updated.get("type"),
        "updated_keys": updated_keys,
    }


@gtm_tool("Failed to update trigger")
async def update_trigger_parameters(
    account_id: str,
    container_id: str,
    trigger_id: str,
    fields: dict,
    workspace_id: str | None = None,
) -> dict:
    """Upsert top-level fields on a GTM trigger in place.

    Fetches the trigger, overwrites each key in ``fields`` on the resource,
    and saves via tagmanager.accounts.containers.workspaces.triggers.update
    with fingerprint-based optimistic concurrency. Keys not in ``fields`` are
    preserved. Mirrors ``update_tag_parameters``' semantics for triggers.

    Wholesale-replace semantic: list-valued fields (``filter``,
    ``customEventFilter``, ``autoEventFilter``) overwrite the existing list.
    Passing ``[]`` clears the list. Passing ``None`` for any *optional* key
    removes that key from the trigger. ``name`` is required by GTM, so
    ``None`` is rejected — omit the key to leave the name unchanged.

    Supported keys:

    - ``name`` (str)
    - ``filter`` / ``customEventFilter`` / ``autoEventFilter`` (list of GTM
      Condition dicts — same shape ``create_trigger``'s ``filters`` accepts)
    - ``interval`` / ``limit`` — timer-trigger Parameter dicts (e.g.
      ``{"type": "integer", "key": "interval", "value": "60000"}``)
    - ``checkValidation`` / ``waitForTags`` — formSubmission-trigger
      Parameter dicts (e.g. ``{"type": "boolean", "key": "checkValidation",
      "value": "true"}``)

    For the {operator, lhs, rhs} ergonomic form, see ``update_trigger_filter``.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_id: The trigger ID to update
        fields: Dict of top-level trigger fields to overwrite
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    return await _update_trigger_parameters_impl(
        account_id=account_id,
        container_id=container_id,
        trigger_id=trigger_id,
        fields=fields,
        workspace_id=workspace_id,
    )


@gtm_tool("Failed to update trigger filter")
async def update_trigger_filter(
    account_id: str,
    container_id: str,
    trigger_id: str,
    conditions: list,
    target: str = "filter",
    workspace_id: str | None = None,
) -> dict:
    """Replace a trigger's filter list using the ergonomic ``{operator, lhs, rhs}`` form.

    Convenience wrapper around ``update_trigger_parameters``. Each condition
    is a dict like ``{"operator": "matchRegex", "lhs": "{{Page Path}}",
    "rhs": "/(create|studio)(?:[?/]|$)"}`` — the tool builds the underlying
    GTM Condition dicts (``arg0``/``arg1`` template parameters) for you.

    Pass ``[]`` for ``conditions`` to clear the list wholesale (same semantic
    as ``update_trigger_parameters``).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_id: The trigger ID to update
        conditions: List of ``{operator, lhs, rhs}`` dicts (or ``[]`` to clear)
        target: Which list to replace — ``filter`` (default), ``customEventFilter``, or ``autoEventFilter``
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    if target not in _TRIGGER_FILTER_KEYS:
        return {
            "status": "error",
            "message": f"target must be one of {list(_TRIGGER_FILTER_KEYS)} (got '{target}')",
        }
    if not isinstance(conditions, list):
        return {"status": "error", "message": "conditions must be a list (use [] to clear)."}

    if conditions:
        try:
            built = _filter_tuples_to_conditions(conditions)
        except ValueError as ve:
            return {"status": "error", "message": str(ve)}
    else:
        built = []

    return await _update_trigger_parameters_impl(
        account_id=account_id,
        container_id=container_id,
        trigger_id=trigger_id,
        fields={target: built},
        workspace_id=workspace_id,
    )


# ---------------------------------------------------------------------------
# Consent settings
# ---------------------------------------------------------------------------

@gtm_tool("Failed to batch update consent settings")
async def update_tags_consent_settings_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    consent_status: str,
    consent_types: list = None,
    workspace_id: str | None = None
) -> dict:
    """Bulk update consent settings for multiple GTM tags at once.

    Applies the same consent configuration to all specified tags.
    Each tag is fetched and updated individually with fingerprint concurrency.
    Use list_gtm_tags first to find the tag IDs you want to update.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag IDs to update
        consent_status: One of "notSet", "notNeeded", or "needed"
        consent_types: List of consent type strings required when status is "needed".
                       Valid types: "ad_storage", "analytics_storage", "ad_user_data",
                       "ad_personalization", "functionality_storage", "personalization_storage",
                       "security_storage"
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    error = _validate_consent_params(consent_status, consent_types)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    workspace_id, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    consent_settings = _build_consent_settings(consent_status, consent_types)

    def apply_consent(tag):
        tag['consentSettings'] = consent_settings
        return tag
    return await _batch_update_tags(client, prefix, tag_ids, apply_consent)


# ---------------------------------------------------------------------------
# Tag parameters
# ---------------------------------------------------------------------------

@gtm_tool("Failed to update tag parameters")
async def update_tag_parameters(
    account_id: str,
    container_id: str,
    tag_id: str,
    parameters: list,
    workspace_id: str | None = None,
) -> dict:
    """Upsert raw GTM parameter dicts on any tag, by ``key``.

    For each item in ``parameters``, replaces the existing parameter with the
    same ``key`` on the tag, or appends it if absent. Other parameters are
    left unchanged. Saves with fingerprint-based optimistic concurrency.

    Each item must be a complete GTM parameter dict matching the API schema:
    ``{"key": str, "type": "template"|"boolean"|"integer"|"list"|"map", ...}``
    with ``value`` for template/boolean/integer, ``list`` for list, or ``map``
    for map. Inspect the tag with ``get_gtm_tag`` first to learn the shape.

    GA4 event tag (type ``gaawe``) recipe — add/overwrite event parameters:
        1. ``get_gtm_tag`` to read existing ``eventParameters``
        2. Build the merged list-of-maps locally
        3. Call this tool with that single ``eventParameters`` entry

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to update
        parameters: List of GTM parameter dicts to upsert by ``key``
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
    if error:
        return {"status": "error", "message": error}
    if not parameters:
        return {"status": "error", "message": "parameters must be a non-empty list."}

    client = get_gtm_client()
    _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    path = f"{ws_parent}/tags/{tag_id}"

    tag = await _run(client.service.accounts().containers().workspaces().tags().get(path=path))

    try:
        tag["parameter"] = _upsert_parameters(tag.get("parameter", []), parameters)
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}

    updated = await _run(
        client.service.accounts().containers().workspaces().tags().update(
            path=path, body=tag, fingerprint=tag.get("fingerprint")
        )
    )

    upserted_keys = [p["key"] for p in parameters]
    return {
        "status": "success",
        "message": f"Upserted {len(upserted_keys)} parameter(s) on tag '{updated.get('name')}'",
        "tag_id": tag_id,
        "tag_name": updated.get("name"),
        "tag_type": updated.get("type"),
        "upserted_keys": upserted_keys,
    }


# ---------------------------------------------------------------------------
# Tag & variable updates
# ---------------------------------------------------------------------------


@gtm_tool("Failed to batch set firing option")
async def set_tags_firing_option_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    firing_option: str,
    workspace_id: str | None = None
) -> dict:
    """Bulk set the tag firing option for multiple GTM tags at once.

    The firing option controls how often a tag may fire relative to events on
    a page:
      - "oncePerLoad"  → once per page load (the GTM UI label is "Once per page")
      - "oncePerEvent" → once per triggering event (can fire multiple times per page)
      - "unlimited"    → every time a firing trigger is satisfied

    Each tag is fetched and updated individually with fingerprint concurrency,
    preserving every other field. Tags already set to ``firing_option`` are
    skipped. Use list_gtm_tags / get_gtm_tag to find tag IDs and inspect their
    current firing option. Changes apply on the next container publish.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag ID strings to update
        firing_option: One of "unlimited", "oncePerEvent", or "oncePerLoad"
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    error = _validate_firing_option(firing_option)
    if error:
        return {"status": "error", "message": error}

    client = get_gtm_client()
    workspace_id, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

    def apply_firing_option(tag):
        if tag.get("tagFiringOption") == firing_option:
            return None
        tag["tagFiringOption"] = firing_option
        return tag
    return await _batch_update_tags(
        client, prefix, tag_ids, apply_firing_option,
        extra_fields_fn=lambda t: {"firing_option": t.get("tagFiringOption")},
        skip_reason=f"Already set to {firing_option}",
    )


@gtm_tool("Failed to create variable")
async def create_gtm_variable(
    account_id: str,
    container_id: str,
    name: str,
    *,
    variable_type: str | None = None,
    parameters: list | None = None,
    javascript: str | None = None,
    datalayer_key: str | None = None,
    notes: str | None = None,
    parent_folder_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    """Create a GTM variable of any type.

    Shortcuts that build the parameter list for you:

    - ``javascript=<source>`` → Custom JavaScript (``jsm``). The source is a full
      anonymous function returning the value, e.g.
      ``"function() { return {{utm_source}} === 'google'; }"``.
    - ``datalayer_key=<key>`` → Data Layer Variable (``v``, dataLayer v2).

    For any other type pass ``variable_type`` (e.g. "c" constant, "u" URL) plus a
    raw GTM ``parameters`` list. ``parameters``, ``javascript`` and
    ``datalayer_key`` are mutually exclusive. For many data layer variables at
    once use ``create_datalayer_variables_batch``.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        name: Display name; tags reference it as ``{{name}}``
        variable_type: GTM variable type; defaults to "jsm" with javascript
        parameters: Raw GTM parameter list (optional)
        javascript: Custom JS source; implies type "jsm" (optional)
        datalayer_key: dataLayer key to read; implies type "v" (optional)
        notes: Notes (optional)
        parent_folder_id: Folder ID (optional)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    if not name:
        return {"status": "error", "message": "name must be a non-empty string"}
    given = [k for k, v in (("parameters", parameters), ("javascript", javascript),
                            ("datalayer_key", datalayer_key)) if v is not None]
    if len(given) > 1:
        return {"status": "error", "message": f"{' and '.join(given)} are mutually exclusive"}
    if javascript is not None:
        if not isinstance(javascript, str) or not javascript.strip():
            return {"status": "error", "message": "javascript must be a non-empty string"}
        if variable_type not in (None, "jsm"):
            return {"status": "error",
                    "message": f"javascript requires type 'jsm', got '{variable_type}'"}
        variable_type = "jsm"
        parameters = [{"type": "template", "key": "javascript", "value": javascript}]
    elif datalayer_key is not None:
        if not isinstance(datalayer_key, str) or not datalayer_key.strip():
            return {"status": "error", "message": "datalayer_key must be a non-empty string"}
        if variable_type not in (None, "v"):
            return {"status": "error",
                    "message": f"datalayer_key requires type 'v', got '{variable_type}'"}
        variable_type = "v"
        parameters = _datalayer_parameters(datalayer_key)
    elif not variable_type:
        return {"status": "error",
                "message": "variable_type is required unless javascript or datalayer_key is given"}

    body = {"name": name, "type": variable_type, "parameter": parameters or []}
    if notes is not None:
        body["notes"] = notes
    if parent_folder_id is not None:
        body["parentFolderId"] = parent_folder_id

    client = get_gtm_client()
    _, parent = await _resolve_workspace_parent(
        client, account_id, container_id, workspace_id
    )
    created = await _run(
        client.service.accounts().containers().workspaces().variables().create(
            parent=parent, body=body,
        )
    )

    return {
        "status": "success",
        "message": f"Variable '{created.get('name')}' created",
        "variable_id": created.get("variableId"),
        "variable_name": created.get("name"),
        "variable_type": created.get("type"),
        "path": created.get("path"),
    }


@gtm_tool("Failed to update variable")
async def update_gtm_variable(
    account_id: str,
    container_id: str,
    variable_id: str,
    *,
    name: str | None = None,
    parameters: list | None = None,
    javascript: str | None = None,
    notes: str | None = None,
    parent_folder_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    """Update an existing GTM variable in place (partial update).

    Fetches the variable, mutates only the fields you passed, then writes
    it back with fingerprint concurrency. Preserves the variable's ID so
    every tag/trigger reference to ``{{variable_name}}`` keeps working.

    For jsm (Custom JavaScript) variables, pass ``javascript=<source>`` as
    a shortcut; the tool builds the right parameter list for you. For any
    variable type, pass ``parameters=<list of GTM parameter dicts>`` to
    replace the parameter list directly. ``parameters`` and ``javascript``
    are mutually exclusive.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variable_id: The variable ID to update
        name: New display name (optional)
        parameters: Raw GTM parameter list, replaces existing (optional)
        javascript: Custom JS source; jsm variables only (optional)
        notes: New notes (optional)
        parent_folder_id: New parent folder ID (optional)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(
        account_id=account_id, container_id=container_id, variable_id=variable_id
    )
    if error:
        return {"status": "error", "message": error}

    if parameters is not None and javascript is not None:
        return {
            "status": "error",
            "message": "parameters and javascript are mutually exclusive",
        }
    if all(v is None for v in (name, parameters, javascript, notes, parent_folder_id)):
        return {
            "status": "error",
            "message": "nothing to update (pass at least one of name, parameters, javascript, notes, parent_folder_id)",
        }

    client = get_gtm_client()
    _, ws_parent = await _resolve_workspace_parent(
        client, account_id, container_id, workspace_id
    )
    path = f"{ws_parent}/variables/{variable_id}"

    variable = await _run(
        client.service.accounts().containers().workspaces().variables().get(path=path)
    )

    if javascript is not None and variable.get("type") != "jsm":
        return {
            "status": "error",
            "message": (
                f"javascript shortcut only valid for jsm variables; "
                f"this variable is type '{variable.get('type')}'"
            ),
        }

    updated_fields: list[str] = []

    if javascript is not None:
        variable["parameter"] = [
            {"type": "template", "key": "javascript", "value": javascript}
        ]
        updated_fields.append("parameters")
    elif parameters is not None:
        variable["parameter"] = parameters
        updated_fields.append("parameters")

    if name is not None:
        variable["name"] = name
        updated_fields.append("name")
    if notes is not None:
        variable["notes"] = notes
        updated_fields.append("notes")
    if parent_folder_id is not None:
        variable["parentFolderId"] = parent_folder_id
        updated_fields.append("parent_folder_id")

    updated = await _run(
        client.service.accounts().containers().workspaces().variables().update(
            path=path, body=variable, fingerprint=variable.get("fingerprint"),
        )
    )

    return {
        "status": "success",
        "message": f"Variable '{updated.get('name')}' updated",
        "variable_id": variable_id,
        "variable_name": updated.get("name"),
        "variable_type": updated.get("type"),
        "updated_fields": updated_fields,
    }


@gtm_tool("Failed to update tag")
async def update_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    *,
    name: str | None = None,
    parameter: list | None = None,
    firing_trigger_ids: list | None = None,
    blocking_trigger_ids: list | None = None,
    setup_tag_name: str | None = None,
    teardown_tag_name: str | None = None,
    stop_on_failure: bool = False,
    tag_firing_option: str | None = None,
    consent_status: str | None = None,
    consent_types: list | None = None,
    notes: str | None = None,
    paused: bool | None = None,
    parent_folder_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    """Update an existing GTM tag in place (partial update).

    Fetches the tag, mutates only the fields you passed, then writes it back
    with fingerprint concurrency — or returns status "noop" without writing
    when the tag already has those values. Preserves the tag's ID so every reference to
    it (including tag-sequencing links) keeps working. Any field left as
    ``None`` is untouched; pass ``firing_trigger_ids=[]`` to explicitly clear a
    tag's own firing triggers (e.g. a tag that should fire only via sequencing).

    Tag sequencing: pass ``teardown_tag_name`` to fire another tag *after* this
    one (this tag's ``teardownTag``), or ``setup_tag_name`` to fire one
    *before* it (``setupTag``). ``stop_on_failure`` maps to
    ``stopTeardownOnFailure`` / ``stopOnSetupFailure`` for whichever you set.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to update
        name: New display name (optional)
        parameter: Raw GTM parameter list, replaces existing (optional)
        firing_trigger_ids: Replace the tag's firing trigger IDs; [] clears them
        blocking_trigger_ids: Replace the tag's blocking (exception) trigger IDs
        setup_tag_name: Name of a tag to fire before this one (setupTag)
        teardown_tag_name: Name of a tag to fire after this one (teardownTag)
        stop_on_failure: stopOnSetupFailure / stopTeardownOnFailure flag
        tag_firing_option: "unlimited", "oncePerEvent", or "oncePerLoad"
        consent_status: "notSet", "notNeeded", or "needed"
        consent_types: Consent types when consent_status is "needed"
        notes: New notes (optional)
        paused: Pause/unpause the tag (optional)
        parent_folder_id: New parent folder ID (optional)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(
        account_id=account_id, container_id=container_id, tag_id=tag_id
    )
    if error:
        return {"status": "error", "message": error}

    mutators = (name, parameter, firing_trigger_ids, blocking_trigger_ids,
                setup_tag_name, teardown_tag_name, tag_firing_option,
                consent_status, notes, paused, parent_folder_id)
    if all(v is None for v in mutators):
        return {
            "status": "error",
            "message": ("nothing to update (pass at least one mutable field, "
                        "e.g. name, parameter, firing_trigger_ids, "
                        "teardown_tag_name, tag_firing_option, paused)"),
        }

    if tag_firing_option is not None:
        error = _validate_firing_option(tag_firing_option)
        if error:
            return {"status": "error", "message": error}

    if consent_status is not None:
        error = _validate_consent_params(consent_status, consent_types)
        if error:
            return {"status": "error", "message": error}

    client = get_gtm_client()
    _, ws_parent = await _resolve_workspace_parent(
        client, account_id, container_id, workspace_id
    )
    path = f"{ws_parent}/tags/{tag_id}"

    tag = await _run(
        client.service.accounts().containers().workspaces().tags().get(path=path)
    )

    original = copy.deepcopy(tag)
    updated_fields: list[str] = []

    if name is not None:
        tag["name"] = name
        updated_fields.append("name")
    if parameter is not None:
        tag["parameter"] = parameter
        updated_fields.append("parameter")
    if firing_trigger_ids is not None:
        tag["firingTriggerId"] = firing_trigger_ids
        updated_fields.append("firing_trigger_ids")
    if blocking_trigger_ids is not None:
        tag["blockingTriggerId"] = blocking_trigger_ids
        updated_fields.append("blocking_trigger_ids")
    if teardown_tag_name is not None:
        tag["teardownTag"] = [
            {"tagName": teardown_tag_name, "stopTeardownOnFailure": stop_on_failure}
        ]
        updated_fields.append("teardown_tag")
    if setup_tag_name is not None:
        tag["setupTag"] = [
            {"tagName": setup_tag_name, "stopOnSetupFailure": stop_on_failure}
        ]
        updated_fields.append("setup_tag")
    if tag_firing_option is not None:
        tag["tagFiringOption"] = tag_firing_option
        updated_fields.append("tag_firing_option")
    if consent_status is not None:
        tag["consentSettings"] = _build_consent_settings(consent_status, consent_types)
        updated_fields.append("consent_settings")
    if notes is not None:
        tag["notes"] = notes
        updated_fields.append("notes")
    if paused is not None:
        tag["paused"] = paused
        updated_fields.append("paused")
    if parent_folder_id is not None:
        tag["parentFolderId"] = parent_folder_id
        updated_fields.append("parent_folder_id")

    if tag == original:
        return {
            "status": "noop",
            "message": f"Tag '{tag.get('name')}' already matches; nothing written",
            "tag_id": tag_id,
            "tag_name": tag.get("name"),
            "tag_type": tag.get("type"),
            "updated_fields": [],
        }
    updated = await _run(
        client.service.accounts().containers().workspaces().tags().update(
            path=path, body=tag, fingerprint=tag.get("fingerprint"),
        )
    )

    return {
        "status": "success",
        "message": f"Tag '{updated.get('name')}' updated",
        "tag_id": tag_id,
        "tag_name": updated.get("name"),
        "tag_type": updated.get("type"),
        "updated_fields": updated_fields,
    }


# ---------------------------------------------------------------------------
# Tag triggers (batch)
# ---------------------------------------------------------------------------

_TRIGGER_FIELDS = {"firing": "firingTriggerId", "blocking": "blockingTriggerId"}
_TRIGGER_ACTIONS = ("add", "remove", "set")


@gtm_tool("Failed to update tag triggers")
async def update_tags_triggers_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    action: str,
    trigger_ids: list,
    kind: str = "firing",
    workspace_id: str | None = None,
) -> dict:
    """Add, remove, or replace firing or blocking triggers on multiple tags.

    - ``action="add"`` — attach ``trigger_ids`` not already on the tag; others kept.
    - ``action="remove"`` — detach ``trigger_ids``; others kept.
    - ``action="set"`` — replace the list with ``trigger_ids`` exactly. ``[]``
      clears it (a tag with no firing trigger stops firing).

    ``kind="blocking"`` targets exception triggers (``blockingTriggerId``): a
    matching blocking trigger stops the tag even when a firing trigger matches.
    Tags that wouldn't change are skipped; each tag is fetched and written with
    fingerprint concurrency. Typical migration: ``create_trigger`` →
    ``action="add"`` new → ``action="remove"`` old → ``delete_trigger`` old.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: Tag IDs to update (max 50)
        action: "add", "remove", or "set"
        trigger_ids: Trigger IDs to add/remove, or the full list for "set"
        kind: "firing" (default) or "blocking"
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    error = _validate_ids(account_id=account_id, container_id=container_id)
    if error:
        return {"status": "error", "message": error}
    if action not in _TRIGGER_ACTIONS:
        return {"status": "error", "message": f"action must be one of {list(_TRIGGER_ACTIONS)}, got '{action}'"}
    if kind not in _TRIGGER_FIELDS:
        return {"status": "error", "message": f"kind must be 'firing' or 'blocking', got '{kind}'"}
    if not isinstance(trigger_ids, list):
        return {"status": "error", "message": "trigger_ids must be a list of trigger ID strings"}
    if not trigger_ids and action != "set":
        return {"status": "error", "message": f"trigger_ids can't be empty for action '{action}'"}
    for i, tid in enumerate(trigger_ids):
        error = _validate_ids(**{f"trigger_ids[{i}]": tid})
        if error:
            return {"status": "error", "message": error}

    client = get_gtm_client()
    _, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
    return await _modify_tag_triggers_batch(
        client, prefix, tag_ids, trigger_ids, action=action, field=_TRIGGER_FIELDS[kind],
    )
