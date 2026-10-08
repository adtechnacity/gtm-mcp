"""
Write MCP tools for Google Tag Manager.

Registers 16 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
publish_gtm_container, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch, set_tags_firing_option_batch, pause_tag, unpause_tag,
delete_tag, delete_gtm_trigger, update_gtm_variable, update_tag, update_gtm_trigger.
"""
import asyncio

from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run,
    MAX_BATCH_SIZE,
    _create_datalayer_var,
    _validate_consent_params, _build_consent_settings,
    _validate_firing_option,
    _validate_ids, _resolve_workspace_parent,
    _batch_update_tags, _paginated_list,
    _dsl_to_gtm_filter, SUPPORTED_TRIGGER_TYPES,
)


# ---------------------------------------------------------------------------
# Pause / unpause shared helper
# ---------------------------------------------------------------------------


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
                {'key': 'dataLayerVersion', 'value': '2', 'type': 'template'},
                {'key': 'setDefaultValue', 'value': 'false', 'type': 'template'},
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


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


def _build_trigger_body(
    trigger_name: str,
    trigger_type: str,
    event_name: str | None,
    filters: list | None,
) -> dict:
    """Build the GTM trigger body for create_trigger.

    Extracted so the surrounding tool can stay below the cognitive-complexity
    threshold. For customEvent triggers, attaches the {{_event}} match when
    event_name is given and the DSL-converted filter list when filters is
    given. For all other trigger types, attaches only the DSL-converted
    filter list (filters must be present; callers guard this upstream).
    """
    body: dict = {"name": trigger_name, "type": trigger_type}

    if trigger_type == "customEvent":
        if event_name:
            body["customEventFilter"] = [
                {
                    "type": "equals",
                    "parameter": [
                        {"key": "arg0", "value": "{{_event}}", "type": "template"},
                        {"key": "arg1", "value": event_name, "type": "template"},
                    ],
                }
            ]
        if filters:
            body["filter"] = [_dsl_to_gtm_filter(f) for f in filters]
    else:
        body["filter"] = [_dsl_to_gtm_filter(f) for f in filters]

    return body


@mcp.tool()
async def create_trigger(
    account_id: str,
    container_id: str,
    trigger_name: str,
    *,
    trigger_type: str = "customEvent",
    event_name: str | None = None,
    filters: list | None = None,
    workspace_id: str = "1"
) -> dict:
    """Create a GTM trigger of the given type, with optional filter conditions.

    Two shapes are supported:

    1. customEvent (default): pass ``event_name`` to fire when
       dataLayer.push({'event': <event_name>}) occurs. ``filters`` may also
       be passed to add additional conditions on top of the event match.
    2. Any other supported type (linkClick, click, pageview, domReady,
       windowLoaded, formSubmission, historyChange, jsError): pass
       ``filters`` (required). Each filter is a friendly dict, e.g.
       ``{"variable": "dl_browser", "operator": "equals", "value": "Chrome",
       "negate": False}``. The tool converts to GTM's verbose filter shape.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_name: Display name for the trigger in GTM
        trigger_type: One of customEvent, linkClick, click, pageview,
            domReady, windowLoaded, formSubmission, historyChange, jsError.
            Defaults to customEvent.
        event_name: For customEvent only — the dataLayer event name to match.
        filters: List of friendly filter dicts (see DSL above). Required for
            non-customEvent types; optional extra filters for customEvent.
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        if trigger_type not in SUPPORTED_TRIGGER_TYPES:
            return {
                "status": "error",
                "message": (
                    f"unsupported trigger_type '{trigger_type}'; "
                    f"supported: {sorted(SUPPORTED_TRIGGER_TYPES)}"
                ),
            }

        if trigger_type == "customEvent":
            if not event_name and not filters:
                return {
                    "status": "error",
                    "message": "customEvent requires event_name or filters",
                }
        else:
            if not filters:
                return {
                    "status": "error",
                    "message": f"trigger_type '{trigger_type}' requires filters",
                }

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(
            client, account_id, container_id, workspace_id
        )

        trigger_body = _build_trigger_body(trigger_name, trigger_type, event_name, filters)

        result = await _run(
            client.service.accounts().containers().workspaces().triggers().create(
                parent=parent,
                body=trigger_body,
            )
        )

        return {
            "status": "success",
            "message": f"Trigger '{trigger_name}' created",
            "trigger_id": result.get("triggerId"),
            "trigger_name": trigger_name,
            "trigger_type": trigger_type,
            "path": result.get("path"),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create trigger: {str(e)}",
        }


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
        workspace_id, prefix = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        def append_trigger(tag):
            existing = tag.get('firingTriggerId', [])
            if trigger_id in existing:
                return None
            tag['firingTriggerId'] = existing + [trigger_id]
            return tag
        return await _batch_update_tags(
            client, prefix, tag_ids, append_trigger,
            extra_fields_fn=lambda t: {"firing_triggers": t.get("firingTriggerId", [])},
            skip_reason="Trigger already attached",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch add firing trigger: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Batch firing-option update
# ---------------------------------------------------------------------------

@mcp.tool()
async def set_tags_firing_option_batch(
    account_id: str,
    container_id: str,
    tag_ids: list,
    firing_option: str,
    workspace_id: str = "1"
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
    try:
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch set firing option: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Pause / unpause
# ---------------------------------------------------------------------------


@mcp.tool()
async def pause_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str = "1",
) -> dict:
    """Pause a GTM tag so it stops firing without deleting it.

    Reversible: use unpause_tag to restore. Useful for safely deprecating
    a tag — pause first, monitor downstream tracking for a few days, then
    delete only if nothing breaks. Changes apply on the next container
    publish; until publish, the live container is unaffected.

    Returns status="noop" if the tag is already paused.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to pause
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        return await _set_tag_paused(client, ws_parent, tag_id, paused=True)
    except Exception as e:
        return {"status": "error", "message": f"Failed to pause tag: {str(e)}"}


@mcp.tool()
async def unpause_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str = "1",
) -> dict:
    """Unpause a previously paused GTM tag so it resumes firing.

    Inverse of pause_tag. Returns status="noop" if the tag is already unpaused.
    Changes apply on the next container publish.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to unpause
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        return await _set_tag_paused(client, ws_parent, tag_id, paused=False)
    except Exception as e:
        return {"status": "error", "message": f"Failed to unpause tag: {str(e)}"}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@mcp.tool()
async def delete_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str = "1",
    force: bool = False,
) -> dict:
    """Delete a GTM tag from a workspace.

    Permanent within the workspace — takes effect at the next
    `publish_gtm_container`. Unpublished workspace deletes can be undone by
    discarding workspace changes in the GTM UI.

    Refuses to delete tags that are not paused unless `force=True`. The
    pause-first workflow exists so the paused-but-still-in-workspace state
    can be monitored for downstream impact before deletion makes it
    irreversible.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
        force: If True, delete even when the tag is not paused. Default False.
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        path = f"{ws_parent}/tags/{tag_id}"

        tag = await _run(
            client.service.accounts().containers().workspaces().tags().get(path=path)
        )
        name = tag.get("name")
        paused = bool(tag.get("paused", False))

        if not paused and not force:
            return {
                "status": "error",
                "code": "not_paused",
                "message": (
                    f"Refusing to delete unpaused tag '{name}' (id={tag_id}). "
                    "Pause it first via pause_tag, or pass force=True."
                ),
                "tag_id": tag_id,
                "tag_name": name,
                "paused": paused,
            }

        await _run(
            client.service.accounts().containers().workspaces().tags().delete(path=path)
        )
        return {
            "status": "success",
            "message": f"Tag '{name}' (id={tag_id}) deleted",
            "tag_id": tag_id,
            "tag_name": name,
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to delete tag: {str(e)}"}


@mcp.tool()
async def delete_gtm_trigger(
    account_id: str,
    container_id: str,
    trigger_id: str,
    workspace_id: str = "1",
    force: bool = False,
) -> dict:
    """Delete a GTM trigger from a workspace.

    Permanent within the workspace — takes effect at the next
    `publish_gtm_container`. Unpublished workspace deletes can be undone by
    discarding workspace changes in the GTM UI.

    Refuses to delete a trigger that any tag still references (as a firing or
    a blocking/exception trigger) unless `force=True`, since deleting a
    referenced trigger silently changes when those tags fire. The error lists
    the referencing tags so they can be repointed first (see `update_tag`).

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_id: The trigger ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
        force: If True, delete even when tags still reference it. Default False.
    """
    try:
        error = _validate_ids(
            account_id=account_id, container_id=container_id, trigger_id=trigger_id
        )
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        path = f"{ws_parent}/triggers/{trigger_id}"

        trigger = await _run(
            client.service.accounts().containers().workspaces().triggers().get(path=path)
        )
        name = trigger.get("name")

        tags = await _paginated_list(
            lambda **kw: client.service.accounts().containers().workspaces().tags().list(
                parent=ws_parent, **kw
            ),
            "tag",
        )
        referencing = []
        for tag in tags:
            for field, label in (("firingTriggerId", "firing"),
                                 ("blockingTriggerId", "blocking")):
                if trigger_id in (tag.get(field) or []):
                    referencing.append({
                        "tag_id": tag.get("tagId"),
                        "tag_name": tag.get("name"),
                        "as": label,
                    })

        if referencing and not force:
            refs = ", ".join(f"{r['tag_name']} (id={r['tag_id']}, {r['as']})"
                             for r in referencing)
            return {
                "status": "error",
                "code": "referenced",
                "message": (
                    f"Refusing to delete trigger '{name}' (id={trigger_id}) — still "
                    f"referenced by {len(referencing)} tag(s): {refs}. Repoint those "
                    "tags first, or pass force=True."
                ),
                "trigger_id": trigger_id,
                "trigger_name": name,
                "referencing_tags": referencing,
            }

        await _run(
            client.service.accounts().containers().workspaces().triggers().delete(path=path)
        )
        return {
            "status": "success",
            "message": f"Trigger '{name}' (id={trigger_id}) deleted",
            "trigger_id": trigger_id,
            "trigger_name": name,
            "referencing_tags": referencing,
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to delete trigger: {str(e)}"}


@mcp.tool()
async def update_gtm_trigger(
    account_id: str,
    container_id: str,
    gtm_trigger_id: str,
    *,
    name: str | None = None,
    filters: list | None = None,
    raw_filter: list | None = None,
    event_name: str | None = None,
    notes: str | None = None,
    parent_folder_id: str | None = None,
    workspace_id: str = "1",
) -> dict:
    """Update an existing GTM trigger in place (partial update).

    Fetches the trigger, mutates only the fields you passed, then writes it
    back with fingerprint concurrency. Preserves the trigger's ID so every
    tag that references it (as a firing or blocking trigger) keeps working —
    no need to repoint anything, unlike delete + recreate.

    NOTE: the ID parameter is named ``gtm_trigger_id`` (not ``trigger_id``) —
    a plain ``trigger_id`` arg was being silently dropped in transit, most
    likely intercepted by an unrelated scheduled-task "trigger" concept that
    also uses that exact parameter name somewhere upstream in the call path.

    ``filters`` replaces the trigger's entire condition list using the same
    friendly DSL as create_trigger, e.g. ``{"variable": "popup", "operator":
    "matchRegex", "value": "\\b(1|hduh|blf)\\b"}``. Pass every condition the
    trigger should keep, not just the one changing — this is a full
    replacement, not a merge. Use ``raw_filter`` instead to pass GTM's
    verbose filter shape directly (e.g. to preserve a "negate" flag or an
    operator the DSL doesn't cover). ``filters`` and ``raw_filter`` are
    mutually exclusive. For customEvent triggers, pass ``event_name`` to
    replace the {{_event}} match condition.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        gtm_trigger_id: The trigger ID to update
        name: New display name (optional)
        filters: Friendly DSL filter list, replaces the trigger's filter list (optional)
        raw_filter: Raw GTM filter list, replaces the trigger's filter list directly (optional)
        event_name: For customEvent triggers — replaces the {{_event}} match (optional)
        notes: New notes (optional)
        parent_folder_id: New parent folder ID (optional)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(
            account_id=account_id, container_id=container_id, gtm_trigger_id=gtm_trigger_id
        )
        if error:
            return {"status": "error", "message": error}

        if filters is not None and raw_filter is not None:
            return {
                "status": "error",
                "message": "filters and raw_filter are mutually exclusive",
            }
        if all(v is None for v in (name, filters, raw_filter, event_name, notes, parent_folder_id)):
            return {
                "status": "error",
                "message": (
                    "nothing to update (pass at least one of name, filters, "
                    "raw_filter, event_name, notes, parent_folder_id)"
                ),
            }

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(
            client, account_id, container_id, workspace_id
        )
        path = f"{ws_parent}/triggers/{gtm_trigger_id}"

        trigger = await _run(
            client.service.accounts().containers().workspaces().triggers().get(path=path)
        )

        if event_name is not None and trigger.get("type") != "customEvent":
            return {
                "status": "error",
                "message": (
                    f"event_name only valid for customEvent triggers; "
                    f"this trigger is type '{trigger.get('type')}'"
                ),
            }

        updated_fields: list[str] = []

        if filters is not None:
            try:
                trigger["filter"] = [_dsl_to_gtm_filter(f) for f in filters]
            except ValueError as e:
                return {"status": "error", "message": str(e)}
            updated_fields.append("filter")
        elif raw_filter is not None:
            trigger["filter"] = raw_filter
            updated_fields.append("filter")

        if event_name is not None:
            trigger["customEventFilter"] = [
                {
                    "type": "equals",
                    "parameter": [
                        {"key": "arg0", "value": "{{_event}}", "type": "template"},
                        {"key": "arg1", "value": event_name, "type": "template"},
                    ],
                }
            ]
            updated_fields.append("event_name")

        if name is not None:
            trigger["name"] = name
            updated_fields.append("name")
        if notes is not None:
            trigger["notes"] = notes
            updated_fields.append("notes")
        if parent_folder_id is not None:
            trigger["parentFolderId"] = parent_folder_id
            updated_fields.append("parent_folder_id")

        updated = await _run(
            client.service.accounts().containers().workspaces().triggers().update(
                path=path, body=trigger, fingerprint=trigger.get("fingerprint"),
            )
        )

        return {
            "status": "success",
            "message": f"Trigger '{updated.get('name')}' updated",
            "trigger_id": gtm_trigger_id,
            "trigger_name": updated.get("name"),
            "trigger_type": updated.get("type"),
            "updated_fields": updated_fields,
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to update trigger: {str(e)}"}


# ---------------------------------------------------------------------------
# Update variable
# ---------------------------------------------------------------------------


@mcp.tool()
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
    workspace_id: str = "1",
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
    try:
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
    except Exception as e:
        return {"status": "error", "message": f"Failed to update variable: {str(e)}"}


@mcp.tool()
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
    workspace_id: str = "1",
) -> dict:
    """Update an existing GTM tag in place (partial update).

    Fetches the tag, mutates only the fields you passed, then writes it back
    with fingerprint concurrency. Preserves the tag's ID so every reference to
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
    try:
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
    except Exception as e:
        return {"status": "error", "message": f"Failed to update tag: {str(e)}"}
