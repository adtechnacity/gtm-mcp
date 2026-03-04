"""
Write/setup MCP tools for Google Tag Manager.

Registers 10 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_ga4_setup, create_facebook_pixel_setup, create_complete_ecommerce_setup,
publish_gtm_container, create_datalayer_variable, create_datalayer_variables_batch,
create_trigger, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch.
"""
import asyncio

from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run,
    HAS_GTM_COMPONENTS,
    _create_components, _create_datalayer_var,
    _validate_consent_params, _build_consent_settings,
    _batch_update_tags,
)

try:
    from gtm_components import GTMWorkflowBuilder
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Setup tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_ga4_setup(account_id: str, container_id: str, measurement_id: str, enhanced_ecommerce: bool = False) -> dict:
    """Create a complete GA4 setup in GTM with config tag, event tags, triggers, and variables.

    Creates the following components in the live GTM workspace:
    - GA4 config tag with the given measurement ID
    - Page view trigger
    - Purchase and add_to_cart event tags
    - Common variables (URL, path, hostname, user ID, event category/action/label)
    If enhanced_ecommerce is True, enables enhanced ecommerce on the config tag.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        measurement_id: GA4 Measurement ID (e.g. "G-XXXXXXXXXX")
        enhanced_ecommerce: Enable enhanced ecommerce tracking (default False)
    """
    try:
        if not HAS_GTM_COMPONENTS:
            return {"status": "error", "message": "GTM components not available"}

        client = get_gtm_client()

        # Build GA4 workflow
        builder = GTMWorkflowBuilder()
        builder.add_google_analytics_4_setup(measurement_id, enhanced_ecommerce)
        builder.add_common_variables()

        components = builder.get_components()
        results = {
            "status": "success",
            "setup_type": "GA4",
            "measurement_id": measurement_id,
            "enhanced_ecommerce": enhanced_ecommerce,
            "created_components": await _create_components(client, account_id, container_id, components),
        }
        return results

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create GA4 setup: {str(e)}"
        }

@mcp.tool()
async def create_facebook_pixel_setup(account_id: str, container_id: str, pixel_id: str) -> dict:
    """Create a Facebook Pixel setup in the live GTM workspace.

    Creates the Facebook Pixel base tag, a page view trigger, and any associated
    event tags in the GTM container. Components are created via the GTM API.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        pixel_id: Facebook Pixel ID (numeric string)
    """
    try:
        if not HAS_GTM_COMPONENTS:
            return {"status": "error", "message": "GTM components not available"}

        client = get_gtm_client()

        # Build Facebook Pixel workflow
        builder = GTMWorkflowBuilder()
        builder.add_facebook_pixel_setup(pixel_id)

        components = builder.get_components()
        results = {
            "status": "success",
            "setup_type": "Facebook Pixel",
            "pixel_id": pixel_id,
            "created_components": await _create_components(client, account_id, container_id, components),
        }
        return results

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create Facebook Pixel setup: {str(e)}"
        }

@mcp.tool()
async def create_complete_ecommerce_setup(account_id: str, container_id: str, ga4_measurement_id: str, facebook_pixel_id: str = None, include_conversion_tracking: bool = True) -> dict:
    """Create a complete ecommerce tracking setup in the live GTM workspace.

    Builds and deploys a full ecommerce tracking stack including:
    - GA4 config tag with enhanced ecommerce enabled
    - Facebook Pixel (optional, if pixel_id provided)
    - Google Ads Conversion Linker (if include_conversion_tracking)
    - Form tracking for #checkout-form
    - Click tracking for .add-to-cart and .buy-now elements
    - Common data layer variables

    All components are created via the GTM API in the default workspace.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        ga4_measurement_id: GA4 Measurement ID (e.g. "G-XXXXXXXXXX")
        facebook_pixel_id: Optional Facebook Pixel ID to include FB tracking
        include_conversion_tracking: Include Google Ads Conversion Linker (default True)
    """
    try:
        if not HAS_GTM_COMPONENTS:
            return {"status": "error", "message": "GTM components not available"}

        client = get_gtm_client()

        # Build complete ecommerce workflow
        builder = GTMWorkflowBuilder()
        builder.add_google_analytics_4_setup(ga4_measurement_id, enhanced_ecommerce=True)

        if facebook_pixel_id:
            builder.add_facebook_pixel_setup(facebook_pixel_id)

        if include_conversion_tracking:
            builder.add_conversion_tracking()

        # Ecommerce specific tracking
        builder.add_form_tracking('#checkout-form')
        builder.add_click_tracking('.add-to-cart', 'add_to_cart')
        builder.add_click_tracking('.buy-now', 'purchase_intent')
        builder.add_common_variables()

        components = builder.get_components()
        results = {
            "status": "success",
            "setup_type": "Complete Ecommerce Workflow",
            "ga4_measurement_id": ga4_measurement_id,
            "facebook_pixel_id": facebook_pixel_id,
            "includes_conversion_tracking": include_conversion_tracking,
            "created_components": await _create_components(client, account_id, container_id, components),
        }
        return results

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create ecommerce setup: {str(e)}"
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
        workspace_id: GTM Workspace ID to publish from (default "1"). Use list_gtm_workspaces to find the correct workspace.
    """
    try:
        client = get_gtm_client()

        result = await asyncio.to_thread(client.publish_version, account_id, container_id, version_name, version_notes, workspace_id)

        publish_result = {
            "status": "success",
            "message": f"Container {container_id} published successfully",
            "version_name": version_name,
            "version_notes": version_notes,
            "published_version": result
        }
        return publish_result

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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()

        # Build the variable body for a Data Layer Variable (type 'v')
        variable_body = {
            'name': variable_name,
            'type': 'v',  # Data Layer Variable type
            'parameter': [
                {'key': 'dataLayerVersion', 'value': '2', 'type': 'template'},
                {'key': 'setDefaultValue', 'value': 'false', 'type': 'template'},
                {'key': 'name', 'value': datalayer_key, 'type': 'template'}
            ]
        }

        parent = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"

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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"
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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"

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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        error = _validate_consent_params(consent_status, consent_types)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        path = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}/tags/{tag_id}"

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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        error = _validate_consent_params(consent_status, consent_types)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        consent_settings = _build_consent_settings(consent_status, consent_types)

        def apply_consent(tag):
            tag['consentSettings'] = consent_settings
            return tag

        prefix = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"
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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()

        def append_trigger(tag):
            existing = tag.get('firingTriggerId', [])
            if trigger_id in existing:
                return None
            tag['firingTriggerId'] = existing + [trigger_id]
            return tag

        prefix = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"
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
