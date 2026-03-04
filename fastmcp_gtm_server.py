#!/usr/bin/env python3
"""
FastMCP GTM Server — MCP server exposing Google Tag Manager API v2 as tools.

Provides 21 tools for managing GTM accounts, containers, workspaces, tags,
triggers, variables, consent settings, and publishing. Uses Google Service
Account credentials via gtm_client_fixed.GTMClient for authentication.

Environment variables:
    GOOGLE_APPLICATION_CREDENTIALS: Path to Google service account JSON key file

Run directly:
    uv run python fastmcp_gtm_server.py

Or via entry point:
    mcp-gtm-server
"""
import asyncio
import json
import logging
import sys
import os
from typing import Any, Dict, List, Optional

# Redirect logging to stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gtm-fastmcp-server")

from mcp.server import FastMCP

# Initialize the MCP server
mcp = FastMCP("gtm-fastmcp-server")

# GTM client initialization
gtm_client = None

def get_gtm_client():
    """Lazy initialization of GTM client"""
    global gtm_client
    if gtm_client is None:
        try:
            from gtm_client_fixed import GTMClient
            gtm_client = GTMClient()
            logger.info("GTM client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GTM client: {e}")
            raise Exception(f"GTM authentication failed: {e}. Please ensure GOOGLE_APPLICATION_CREDENTIALS is set.")
    return gtm_client

# Load GTM components
try:
    from gtm_components import GTMComponentTemplates, GTMWorkflowBuilder
    HAS_GTM_COMPONENTS = True
    logger.info("GTM components loaded successfully")
except ImportError as e:
    logger.error(f"Failed to load GTM components: {e}")
    HAS_GTM_COMPONENTS = False

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
        client = get_gtm_client()
        containers = await client.list_containers(account_id)

        result = {
            "status": "success",
            "message": "GTM API connection successful",
            "account_id": account_id,
            "containers_found": len(containers),
            "containers": [{"name": c.get("name", "Unknown"), "containerId": c.get("containerId", "Unknown")} for c in containers[:5]]
        }
        return result
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
        client = get_gtm_client()
        containers = await client.list_containers(account_id)

        result = {
            "status": "success",
            "account_id": account_id,
            "total_containers": len(containers),
            "containers": containers
        }
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list containers: {str(e)}"
        }

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
            "created_components": []
        }

        # Create variables first
        for variable in components['variables']:
            try:
                result = await client.create_variable(
                    account_id, container_id,
                    variable['name'], variable['type'],
                    variable.get('parameters', {})
                )
                results["created_components"].append({
                    "type": "variable",
                    "name": variable['name'],
                    "status": "success",
                    "id": result.get('variableId')
                })
            except Exception as e:
                results["created_components"].append({
                    "type": "variable",
                    "name": variable['name'],
                    "status": "error",
                    "error": str(e)
                })

        # Create triggers
        for trigger in components['triggers']:
            try:
                result = await client.create_trigger(
                    account_id, container_id,
                    trigger['name'], trigger['type'],
                    trigger.get('filters', [])
                )
                results["created_components"].append({
                    "type": "trigger",
                    "name": trigger['name'],
                    "status": "success",
                    "id": result.get('triggerId')
                })
            except Exception as e:
                results["created_components"].append({
                    "type": "trigger",
                    "name": trigger['name'],
                    "status": "error",
                    "error": str(e)
                })

        # Create tags
        for tag in components['tags']:
            try:
                result = await client.create_tag(
                    account_id, container_id,
                    tag['name'], tag['type'],
                    tag.get('parameters', {})
                )
                results["created_components"].append({
                    "type": "tag",
                    "name": tag['name'],
                    "status": "success",
                    "id": result.get('tagId')
                })
            except Exception as e:
                results["created_components"].append({
                    "type": "tag",
                    "name": tag['name'],
                    "status": "error",
                    "error": str(e)
                })
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
            "created_components": []
        }


        # Create triggers and tags
        for trigger in components['triggers']:
            try:
                result = await client.create_trigger(
                    account_id, container_id,
                    trigger['name'], trigger['type'],
                    trigger.get('filters', [])
                )
                results["created_components"].append({
                    "type": "trigger",
                    "name": trigger['name'],
                    "status": "success",
                    "id": result.get('triggerId')
                })
            except Exception as e:
                results["created_components"].append({
                    "type": "trigger",
                    "name": trigger['name'],
                    "status": "error",
                    "error": str(e)
                })

        for tag in components['tags']:
            try:
                result = await client.create_tag(
                    account_id, container_id,
                    tag['name'], tag['type'],
                    tag.get('parameters', {})
                )
                results["created_components"].append({
                    "type": "tag",
                    "name": tag['name'],
                    "status": "success",
                    "id": result.get('tagId')
                })
            except Exception as e:
                results["created_components"].append({
                    "type": "tag",
                    "name": tag['name'],
                    "status": "error",
                    "error": str(e)
                })
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
            "created_components": []
        }


        # Create all components
        all_components = [
            ("variable", components['variables']),
            ("trigger", components['triggers']),
            ("tag", components['tags'])
        ]

        for component_type, component_list in all_components:
            for component in component_list:
                try:
                    if component_type == "variable":
                        result = await client.create_variable(
                            account_id, container_id,
                            component['name'], component['type'],
                            component.get('parameters', {})
                        )
                    elif component_type == "trigger":
                        result = await client.create_trigger(
                            account_id, container_id,
                            component['name'], component['type'],
                            component.get('filters', [])
                        )
                    elif component_type == "tag":
                        result = await client.create_tag(
                            account_id, container_id,
                            component['name'], component['type'],
                            component.get('parameters', {})
                        )

                    results["created_components"].append({
                        "type": component_type,
                        "name": component['name'],
                        "status": "success",
                        "id": result.get(f'{component_type}Id')
                    })
                except Exception as e:
                    results["created_components"].append({
                        "type": component_type,
                        "name": component['name'],
                        "status": "error",
                        "error": str(e)
                    })
        return results

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create ecommerce setup: {str(e)}"
        }

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

        result = await client.publish_version(account_id, container_id, version_name, version_notes, workspace_id)

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

        result = {
            "status": "success",
            "template_type": "GA4 Configuration Tag",
            "measurement_id": measurement_id,
            "template": ga4_tag,
            "usage": "Copy this JSON template and import it into your GTM container"
        }
        return result

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to generate GA4 template: {str(e)}"
        }


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

        result = client.service.accounts().containers().workspaces().variables().create(
            parent=parent,
            body=variable_body
        ).execute()

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

        results = {
            "status": "success",
            "created": [],
            "failed": []
        }

        for var in variables:
            try:
                variable_body = {
                    'name': var['name'],
                    'type': 'v',
                    'parameter': [
                        {'key': 'dataLayerVersion', 'value': '2', 'type': 'template'},
                        {'key': 'setDefaultValue', 'value': 'false', 'type': 'template'},
                        {'key': 'name', 'value': var['key'], 'type': 'template'}
                    ]
                }

                result = client.service.accounts().containers().workspaces().variables().create(
                    parent=parent,
                    body=variable_body
                ).execute()

                results["created"].append({
                    "name": var['name'],
                    "key": var['key'],
                    "variable_id": result.get('variableId')
                })
            except Exception as e:
                results["failed"].append({
                    "name": var['name'],
                    "key": var['key'],
                    "error": str(e)
                })

        if results["failed"]:
            results["status"] = "partial" if results["created"] else "error"

        results["summary"] = f"Created {len(results['created'])}/{len(variables)} variables"
        return results
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create Data Layer Variables: {str(e)}"
        }

@mcp.tool()
async def list_gtm_variables(account_id: str, container_id: str, workspace_id: str = "1") -> dict:
    """List all variables in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.variables.list.
    Returns each variable's name, type, and ID.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"

        result = client.service.accounts().containers().workspaces().variables().list(
            parent=parent
        ).execute()

        variables = result.get('variable', [])

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
        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}"

        result = client.service.accounts().containers().workspaces().list(
            parent=parent
        ).execute()

        workspaces = result.get('workspace', [])

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
async def list_gtm_accounts() -> dict:
    """List all GTM accounts the authenticated user has access to.

    Calls tagmanager.accounts.list. Returns each account's name, ID, and path.
    This is typically the first discovery call — use the returned account IDs
    with list_gtm_containers to find containers.
    """
    try:
        client = get_gtm_client()

        result = client.service.accounts().list().execute()

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
async def list_gtm_tags(account_id: str, container_id: str, workspace_id: str = "1") -> dict:
    """List all tags in a GTM workspace, including their consent settings.

    Calls tagmanager.accounts.containers.workspaces.tags.list.
    Returns each tag's name, type, ID, firing/blocking triggers, pause state,
    and parsed consent configuration. Use this to audit which tags have consent
    requirements configured.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"

        result = client.service.accounts().containers().workspaces().tags().list(
            parent=parent
        ).execute()

        tags = result.get('tag', [])

        def parse_consent_settings(tag):
            cs = tag.get('consentSettings', {})
            consent_status = cs.get('consentStatus', 'notSet')
            consent_types = []
            consent_type_param = cs.get('consentType', {})
            if consent_type_param.get('type') == 'list':
                for item in consent_type_param.get('list', []):
                    consent_types.append(item.get('value', ''))
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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        path = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}/tags/{tag_id}"

        tag = client.service.accounts().containers().workspaces().tags().get(
            path=path
        ).execute()

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
        if consent_status not in ("notSet", "notNeeded", "needed"):
            return {
                "status": "error",
                "message": f"Invalid consent_status '{consent_status}'. Must be 'notSet', 'notNeeded', or 'needed'."
            }

        if consent_status == "needed" and not consent_types:
            return {
                "status": "error",
                "message": "consent_types is required when consent_status is 'needed'."
            }

        client = get_gtm_client()
        path = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}/tags/{tag_id}"

        # Get the existing tag
        tag = client.service.accounts().containers().workspaces().tags().get(
            path=path
        ).execute()

        # Build consent settings
        consent_settings = {
            "consentStatus": consent_status
        }

        if consent_status == "needed" and consent_types:
            consent_settings["consentType"] = {
                "type": "list",
                "list": [
                    {"type": "template", "value": ct}
                    for ct in consent_types
                ]
            }

        tag['consentSettings'] = consent_settings

        # Update the tag
        updated = client.service.accounts().containers().workspaces().tags().update(
            path=path,
            body=tag,
            fingerprint=tag.get('fingerprint')
        ).execute()

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
        if consent_status not in ("notSet", "notNeeded", "needed"):
            return {
                "status": "error",
                "message": f"Invalid consent_status '{consent_status}'. Must be 'notSet', 'notNeeded', or 'needed'."
            }

        if consent_status == "needed" and not consent_types:
            return {
                "status": "error",
                "message": "consent_types is required when consent_status is 'needed'."
            }

        client = get_gtm_client()

        # Build consent settings
        consent_settings = {
            "consentStatus": consent_status
        }
        if consent_status == "needed" and consent_types:
            consent_settings["consentType"] = {
                "type": "list",
                "list": [
                    {"type": "template", "value": ct}
                    for ct in consent_types
                ]
            }

        results = {
            "status": "success",
            "updated": [],
            "failed": []
        }

        for tag_id in tag_ids:
            try:
                path = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}/tags/{tag_id}"

                # Get the existing tag
                tag = client.service.accounts().containers().workspaces().tags().get(
                    path=path
                ).execute()

                tag['consentSettings'] = consent_settings

                # Update
                updated = client.service.accounts().containers().workspaces().tags().update(
                    path=path,
                    body=tag,
                    fingerprint=tag.get('fingerprint')
                ).execute()

                results["updated"].append({
                    "tag_id": tag_id,
                    "tag_name": updated.get('name')
                })
            except Exception as e:
                results["failed"].append({
                    "tag_id": tag_id,
                    "error": str(e)
                })

        if results["failed"]:
            results["status"] = "partial" if results["updated"] else "error"

        results["summary"] = f"Updated {len(results['updated'])}/{len(tag_ids)} tags"
        return results
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch update consent settings: {str(e)}"
        }


@mcp.tool()
async def list_gtm_triggers(account_id: str, container_id: str, workspace_id: str = "1") -> dict:
    """List all triggers in a GTM workspace.

    Calls tagmanager.accounts.containers.workspaces.triggers.list.
    Returns each trigger's name, type, ID, filter conditions, and custom event filters.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        parent = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}"

        result = client.service.accounts().containers().workspaces().triggers().list(
            parent=parent
        ).execute()

        triggers = result.get('trigger', [])

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
        workspace_id: GTM Workspace ID (default "1")
    """
    try:
        client = get_gtm_client()
        path = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}/variables/{variable_id}"

        client.service.accounts().containers().workspaces().variables().delete(
            path=path
        ).execute()

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

        result = client.service.accounts().containers().workspaces().triggers().create(
            parent=parent,
            body=trigger_body
        ).execute()

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

        results = {
            "status": "success",
            "updated": [],
            "skipped": [],
            "failed": []
        }

        for tag_id in tag_ids:
            try:
                path = f"accounts/{account_id}/containers/{container_id}/workspaces/{workspace_id}/tags/{tag_id}"

                # Get the existing tag
                tag = client.service.accounts().containers().workspaces().tags().get(
                    path=path
                ).execute()

                # Check if trigger is already attached
                existing_triggers = tag.get('firingTriggerId', [])
                if trigger_id in existing_triggers:
                    results["skipped"].append({
                        "tag_id": tag_id,
                        "tag_name": tag.get('name'),
                        "reason": "Trigger already attached"
                    })
                    continue

                # Append the new trigger ID
                tag['firingTriggerId'] = existing_triggers + [trigger_id]

                # Update the tag
                updated = client.service.accounts().containers().workspaces().tags().update(
                    path=path,
                    body=tag,
                    fingerprint=tag.get('fingerprint')
                ).execute()

                results["updated"].append({
                    "tag_id": tag_id,
                    "tag_name": updated.get('name'),
                    "firing_triggers": updated.get('firingTriggerId', [])
                })
            except Exception as e:
                results["failed"].append({
                    "tag_id": tag_id,
                    "error": str(e)
                })

        if results["failed"]:
            results["status"] = "partial" if results["updated"] else "error"

        total = len(tag_ids)
        results["summary"] = (
            f"Updated {len(results['updated'])}/{total} tags, "
            f"skipped {len(results['skipped'])}, "
            f"failed {len(results['failed'])}"
        )
        return results
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to batch add firing trigger: {str(e)}"
        }


def main():
    """Entry point for the MCP GTM server."""
    logger.info("Starting FastMCP GTM Server...")
    mcp.run()


if __name__ == '__main__':
    main()
