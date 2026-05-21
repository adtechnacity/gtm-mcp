"""
Write MCP tools for Google Tag Manager.

Registers 19 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
create_js_variable, publish_gtm_container, update_tag_consent_settings,
update_tags_consent_settings_batch, update_tag_html, update_tag_parameters,
update_trigger_parameters, update_trigger_filter,
delete_tag, delete_trigger, add_firing_trigger_to_tags_batch,
add_blocking_trigger_to_tags_batch, set_firing_triggers_on_tags_batch,
remove_firing_trigger_from_tags_batch, remove_blocking_trigger_from_tags_batch.
"""
import asyncio

from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run,
    MAX_BATCH_SIZE,
    _create_datalayer_var,
    _validate_consent_params, _build_consent_settings,
    _validate_ids, _resolve_workspace_parent,
    _batch_update_tags,
    _append_trigger_to_tags_batch,
    _remove_trigger_from_tags_batch,
    _set_triggers_on_tags_batch,
    _upsert_parameters,
    _validate_trigger_filters,
    _filter_tuples_to_conditions,
)


# ---------------------------------------------------------------------------
# Tag creation
# ---------------------------------------------------------------------------

@mcp.tool()
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
    workspace_id: str = "1",
) -> dict:
    """Create any tag in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.tags.create to create a tag
    of any type (GA4, Custom HTML, Facebook Pixel, Google Ads, etc.).

    The ``parameter`` list uses GTM's native format — each item is a dict with
    ``key``, ``value``, and ``type`` (usually ``"template"``). Use ``get_gtm_tag``
    on an existing tag to see the parameter format for a given tag type, or use
    ``generate_ga4_template`` for GA4-specific templates.

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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create tag: {str(e)}",
        }


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

@mcp.tool()
async def publish_gtm_container(account_id: str, container_id: str, version_name: str, version_notes: str = "Published via MCP", workspace_id: str = "1") -> dict:
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
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, _ = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        result = await asyncio.to_thread(client.publish_version, account_id, container_id, version_name, version_notes, workspace_id)

        version = result.get("containerVersion", {})
        return {
            "status": "success",
            "message": f"Container {container_id} published successfully",
            "version_name": version_name,
            "version_notes": version_notes,
            "version_id": version.get("containerVersionId"),
            "path": version.get("path"),
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to publish container: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Data Layer Variables
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_datalayer_variable(account_id: str, container_id: str, variable_name: str, datalayer_key: str, workspace_id: str = "1") -> dict:
    """Create a single Data Layer Variable in a GTM workspace.

    Creates a variable of type 'v' (Data Layer Variable) that reads a specific
    key from the dataLayer. Uses dataLayer version 2.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variable_name: Display name for the variable in GTM (e.g., "DLV - fs_order_id")
        datalayer_key: The dataLayer key to read (e.g., "fs_order_id")
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        variable_body = {
            'name': variable_name,
            'type': 'v',  # Data Layer Variable type
            'parameter': [
                {'key': 'dataLayerVersion', 'value': '2', 'type': 'integer'},
                {'key': 'setDefaultValue', 'value': 'false', 'type': 'boolean'},
                {'key': 'name', 'value': datalayer_key, 'type': 'template'}
            ]
        }

        result = await _run(client.service.accounts().containers().workspaces().variables().create(
            parent=parent,
            body=variable_body
        ))

        return {
            "status": "success",
            "message": f"Data Layer Variable '{variable_name}' created successfully",
            "variable_id": result.get('variableId'),
            "variable_name": variable_name,
            "datalayer_key": datalayer_key,
            "path": result.get('path')
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create Data Layer Variable: {str(e)}"
        }

@mcp.tool()
async def create_datalayer_variables_batch(account_id: str, container_id: str, variables: list, workspace_id: str = "1") -> dict:
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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create Data Layer Variables: {str(e)}"
        }


@mcp.tool()
async def create_js_variable(
    account_id: str,
    container_id: str,
    variable_name: str,
    javascript: str,
    workspace_id: str = "1"
) -> dict:
    """Create a Custom JavaScript variable in a GTM workspace.

    Creates a variable of type ``jsm`` whose value is computed by the provided
    JavaScript function. The ``javascript`` argument must be a full anonymous
    function expression that returns the value — GTM evaluates it at tag fire
    time and uses the return value.

    Example:

        create_js_variable(
            account_id, container_id,
            variable_name="JS - is_google_yt_el_source",
            javascript="function() { return {{utm_source}} === 'google_yt_el'; }",
        )

    Reference other GTM variables inside the function with ``{{Variable Name}}``
    — the GTM parameter ``type`` is ``template`` so placeholders are resolved
    before execution.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variable_name: Display name for the variable in GTM (e.g., "JS - is_google_yt_el_source")
        javascript: The function source as a string (must be a function that returns a value)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}
        if not isinstance(javascript, str) or not javascript.strip():
            return {"status": "error", "message": "javascript must be a non-empty string"}

        client = get_gtm_client()
        _, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        variable_body = {
            'name': variable_name,
            'type': 'jsm',
            'parameter': [
                {'key': 'javascript', 'value': javascript, 'type': 'template'}
            ]
        }

        result = await _run(client.service.accounts().containers().workspaces().variables().create(
            parent=parent,
            body=variable_body
        ))

        return {
            "status": "success",
            "message": f"Custom JavaScript variable '{variable_name}' created successfully",
            "variable_id": result.get('variableId'),
            "variable_name": variable_name,
            "path": result.get('path')
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create Custom JavaScript variable: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

_VALID_TRIGGER_TYPES = {
    "pageview", "domReady", "windowLoaded", "customEvent", "click", "linkClick",
    "formSubmission", "timer", "elementVisibility", "historyChange", "scrollDepth",
    "youTubeVideo", "init", "consentInit", "pageviewGtm", "serverPageview",
    "triggerGroup",
}


@mcp.tool()
async def create_trigger(
    account_id: str,
    container_id: str,
    trigger_name: str,
    event_name: str | None = None,
    trigger_type: str = "customEvent",
    filters: list[dict] | None = None,
    workspace_id: str = "1"
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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create trigger: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Tag deletion
# ---------------------------------------------------------------------------

@mcp.tool()
async def delete_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str = "1"
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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete tag: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Trigger deletion
# ---------------------------------------------------------------------------

@mcp.tool()
async def delete_trigger(
    account_id: str,
    container_id: str,
    trigger_id: str,
    workspace_id: str = "1"
) -> dict:
    """Delete a trigger from a GTM workspace.

    Removes the trigger resource entirely. Tags that reference this trigger via
    ``firingTriggerId`` or ``blockingTriggerId`` will have dangling references
    after deletion — detach the trigger from tags first via
    ``remove_firing_trigger_from_tags_batch`` or
    ``remove_blocking_trigger_from_tags_batch``, or by replacing the firing list
    via ``set_firing_triggers_on_tags_batch``.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_id: The trigger ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete trigger: {str(e)}"
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
    workspace_id: str = "1",
) -> dict:
    """Shared implementation for update_trigger_parameters / update_trigger_filter."""
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update trigger parameters: {str(e)}",
        }


@mcp.tool()
async def update_trigger_parameters(
    account_id: str,
    container_id: str,
    trigger_id: str,
    fields: dict,
    workspace_id: str = "1",
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


@mcp.tool()
async def update_trigger_filter(
    account_id: str,
    container_id: str,
    trigger_id: str,
    conditions: list,
    target: str = "filter",
    workspace_id: str = "1",
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

@mcp.tool()
async def update_tag_consent_settings(
    account_id: str,
    container_id: str,
    tag_id: str,
    consent_status: str,
    consent_types: list = None,
    workspace_id: str = "1"
) -> dict:
    """Update consent settings for a specific GTM tag.

    Fetches the tag, replaces its consentSettings, then updates via
    tagmanager.accounts.containers.workspaces.tags.update with fingerprint
    for optimistic concurrency.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to update
        consent_status: One of "notSet", "notNeeded", or "needed"
        consent_types: List of consent type strings required when status is "needed".
                       Valid types: "ad_storage", "analytics_storage", "ad_user_data",
                       "ad_personalization", "functionality_storage", "personalization_storage",
                       "security_storage"
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
        if error:
            return {"status": "error", "message": error}
        error = _validate_consent_params(consent_status, consent_types)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        path = f"{ws_parent}/tags/{tag_id}"

        tag = await _run(client.service.accounts().containers().workspaces().tags().get(path=path))
        tag['consentSettings'] = _build_consent_settings(consent_status, consent_types)

        updated = await _run(client.service.accounts().containers().workspaces().tags().update(
            path=path, body=tag, fingerprint=tag.get('fingerprint')
        ))

        return {
            "status": "success",
            "message": f"Consent settings updated for tag '{updated.get('name')}'",
            "tag_id": tag_id,
            "tag_name": updated.get('name'),
            "consent_status": consent_status,
            "consent_types": consent_types or []
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update consent settings: {str(e)}"
        }


@mcp.tool()
async def update_tags_consent_settings_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    consent_status: str,
    consent_types: list = None,
    workspace_id: str = "1"
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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch update consent settings: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Update tag HTML
# ---------------------------------------------------------------------------

@mcp.tool()
async def update_tag_html(
    account_id: str,
    container_id: str,
    tag_id: str,
    html: str,
    workspace_id: str = "1",
) -> dict:
    """Update the HTML content of a Custom HTML tag.

    Fetches the tag, replaces its ``html`` parameter value, and saves it back
    using fingerprint-based optimistic concurrency. Only works on tags of type
    ``html`` (Custom HTML). Returns an error if the tag is not a Custom HTML
    tag or if the ``html`` parameter is not found.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to update
        html: The new HTML content (including <script> tags)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update tag HTML: {str(e)}",
        }


@mcp.tool()
async def update_tag_parameters(
    account_id: str,
    container_id: str,
    tag_id: str,
    parameters: list,
    workspace_id: str = "1",
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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update tag parameters: {str(e)}",
        }


# ---------------------------------------------------------------------------
# Batch trigger attachment
# ---------------------------------------------------------------------------

@mcp.tool()
async def add_firing_trigger_to_tags_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    trigger_id: str,
    workspace_id: str = "1"
) -> dict:
    """Add an additional firing trigger to multiple GTM tags without removing their existing triggers.

    Fetches each tag, appends the new trigger ID to its firingTriggerId list,
    and updates it with fingerprint concurrency. Skips tags that already have
    the trigger attached.
    Use list_gtm_tags to find tag IDs and list_gtm_triggers or create_trigger to get a trigger ID.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag ID strings to update
        trigger_id: The trigger ID to add as a firing trigger
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        return await _append_trigger_to_tags_batch(
            client, prefix, tag_ids, trigger_id,
            field="firingTriggerId",
            label="firing_triggers",
            skip_reason="Trigger already attached",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch add firing trigger: {str(e)}"
        }


@mcp.tool()
async def add_blocking_trigger_to_tags_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    trigger_id: str,
    workspace_id: str = "1"
) -> dict:
    """Add a blocking (exception) trigger to multiple GTM tags.

    Fetches each tag, appends the trigger ID to its blockingTriggerId list,
    and updates it with fingerprint concurrency. Skips tags that already have
    the trigger attached. A blocking trigger prevents the tag from firing
    whenever its conditions match, even if a firing trigger also matches.

    Use list_gtm_tags to find tag IDs and list_gtm_triggers or create_trigger
    to get a trigger ID.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag ID strings to update
        trigger_id: The trigger ID to add as a blocking (exception) trigger
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        return await _append_trigger_to_tags_batch(
            client, prefix, tag_ids, trigger_id,
            field="blockingTriggerId",
            label="blocking_triggers",
            skip_reason="Blocking trigger already attached",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch add blocking trigger: {str(e)}"
        }


@mcp.tool()
async def set_firing_triggers_on_tags_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    trigger_ids: list,
    workspace_id: str = "1"
) -> dict:
    """Replace the firing trigger list on multiple GTM tags.

    Overwrites each tag's ``firingTriggerId`` with ``trigger_ids`` verbatim —
    existing firing triggers not in ``trigger_ids`` are detached, and triggers
    in ``trigger_ids`` not already attached are added. Useful for migrating
    tags from an old trigger to a new one in a single call.

    Skips tags whose firing list is already equal to ``trigger_ids``. Uses
    fingerprint-based optimistic concurrency per tag.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag ID strings to update
        trigger_ids: The complete list of trigger IDs to set as firing triggers.
                     Pass an empty list to detach all firing triggers (tag will
                     not fire until a trigger is added back).
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}
        if not isinstance(trigger_ids, list):
            return {"status": "error", "message": "trigger_ids must be a list of trigger ID strings"}
        for i, tid in enumerate(trigger_ids):
            if not isinstance(tid, str) or not tid.isdigit():
                return {"status": "error", "message": f"trigger_ids[{i}] must be a numeric string"}

        client = get_gtm_client()
        _, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        return await _set_triggers_on_tags_batch(
            client, prefix, tag_ids, trigger_ids,
            field="firingTriggerId",
            label="firing_triggers",
            skip_reason="Firing triggers already match",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch set firing triggers: {str(e)}"
        }


@mcp.tool()
async def remove_firing_trigger_from_tags_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    trigger_id: str,
    workspace_id: str = "1"
) -> dict:
    """Remove a firing trigger from multiple GTM tags.

    Detaches ``trigger_id`` from each tag's ``firingTriggerId`` list. Other
    firing triggers on the tag are preserved. Skips tags that do not have the
    trigger attached. Uses fingerprint-based optimistic concurrency.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag ID strings to update
        trigger_id: The trigger ID to detach from firingTriggerId
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        return await _remove_trigger_from_tags_batch(
            client, prefix, tag_ids, trigger_id,
            field="firingTriggerId",
            label="firing_triggers",
            skip_reason="Firing trigger not attached",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch remove firing trigger: {str(e)}"
        }


@mcp.tool()
async def remove_blocking_trigger_from_tags_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    trigger_id: str,
    workspace_id: str = "1"
) -> dict:
    """Remove a blocking (exception) trigger from multiple GTM tags.

    Detaches ``trigger_id`` from each tag's ``blockingTriggerId`` list. Other
    blocking triggers on the tag are preserved. Skips tags that do not have
    the trigger attached. Uses fingerprint-based optimistic concurrency.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_ids: List of tag ID strings to update
        trigger_id: The trigger ID to detach from blockingTriggerId
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, trigger_id=trigger_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        return await _remove_trigger_from_tags_batch(
            client, prefix, tag_ids, trigger_id,
            field="blockingTriggerId",
            label="blocking_triggers",
            skip_reason="Blocking trigger not attached",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch remove blocking trigger: {str(e)}"
        }
