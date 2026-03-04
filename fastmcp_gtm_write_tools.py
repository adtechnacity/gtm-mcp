"""
Write MCP tools for Google Tag Manager.

Registers 8 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
publish_gtm_container, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch.
"""
import asyncio

from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run,
    MAX_BATCH_SIZE,
    _create_datalayer_var,
    _validate_consent_params, _build_consent_settings,
    _validate_ids, _resolve_workspace_parent,
    _batch_update_tags,
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

@mcp.tool()
async def create_trigger(
    account_id: str,
    container_id: str,
    trigger_name: str,
    event_name: str,
    workspace_id: str = "1"
) -> dict:
    """Create a custom event trigger in a GTM workspace.

    Creates a trigger of type 'customEvent' that fires when a matching event
    is pushed to the dataLayer. For example, to fire on
    dataLayer.push({'event': 'consent_update'}), set event_name to "consent_update".

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_name: Display name for the trigger in GTM (e.g., "CE - consent_update")
        event_name: The custom event name to match (e.g., "consent_update")
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)

        trigger_body = {
            'name': trigger_name,
            'type': 'customEvent',
            'customEventFilter': [
                {
                    'type': 'equals',
                    'parameter': [
                        {'key': 'arg0', 'value': '{{_event}}', 'type': 'template'},
                        {'key': 'arg1', 'value': event_name, 'type': 'template'}
                    ]
                }
            ]
        }

        result = await _run(client.service.accounts().containers().workspaces().triggers().create(
            parent=parent,
            body=trigger_body
        ))

        return {
            "status": "success",
            "message": f"Custom event trigger '{trigger_name}' created successfully",
            "trigger_id": result.get('triggerId'),
            "trigger_name": trigger_name,
            "event_name": event_name,
            "path": result.get('path')
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create trigger: {str(e)}"
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
