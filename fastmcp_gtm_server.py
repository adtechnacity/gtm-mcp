#!/usr/bin/env python3
"""
FastMCP GTM Server - 올바른 @mcp.tool() 데코레이터 방식
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
            credentials_file = os.getenv('GTM_CREDENTIALS_FILE', 'credentials.json')
            token_file = os.getenv('GTM_TOKEN_FILE', 'token.json')
            gtm_client = GTMClient(credentials_file, token_file)
            logger.info("GTM client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GTM client: {e}")
            raise Exception(f"GTM authentication failed: {e}. Please ensure credentials.json is properly configured.")
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
def test_gtm_connection(account_id: str) -> dict:
    """Test GTM API connection and authentication"""
    try:
        client = get_gtm_client()
        # This will be sync, but we'll make it work
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        containers = loop.run_until_complete(client.list_containers(account_id))
        loop.close()
        
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
def list_gtm_containers(account_id: str) -> dict:
    """List all GTM containers in an account"""
    try:
        client = get_gtm_client()
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        containers = loop.run_until_complete(client.list_containers(account_id))
        loop.close()
        
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
def create_ga4_setup(account_id: str, container_id: str, measurement_id: str, enhanced_ecommerce: bool = False) -> dict:
    """Create complete GA4 setup in GTM (실제 GTM에 생성)"""
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
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create variables first
        for variable in components['variables']:
            try:
                result = loop.run_until_complete(client.create_variable(
                    account_id, container_id, 
                    variable['name'], variable['type'], 
                    variable.get('parameters', {})
                ))
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
                result = loop.run_until_complete(client.create_trigger(
                    account_id, container_id,
                    trigger['name'], trigger['type'],
                    trigger.get('filters', [])
                ))
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
                result = loop.run_until_complete(client.create_tag(
                    account_id, container_id,
                    tag['name'], tag['type'],
                    tag.get('parameters', {})
                ))
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
        
        loop.close()
        return results
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create GA4 setup: {str(e)}"
        }

@mcp.tool()
def create_facebook_pixel_setup(account_id: str, container_id: str, pixel_id: str) -> dict:
    """Create Facebook Pixel setup in GTM (실제 GTM에 생성)"""
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
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create triggers and tags
        for trigger in components['triggers']:
            try:
                result = loop.run_until_complete(client.create_trigger(
                    account_id, container_id,
                    trigger['name'], trigger['type'],
                    trigger.get('filters', [])
                ))
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
                result = loop.run_until_complete(client.create_tag(
                    account_id, container_id,
                    tag['name'], tag['type'],
                    tag.get('parameters', {})
                ))
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
        
        loop.close()
        return results
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create Facebook Pixel setup: {str(e)}"
        }

@mcp.tool()
def create_complete_ecommerce_setup(account_id: str, container_id: str, ga4_measurement_id: str, facebook_pixel_id: str = None, include_conversion_tracking: bool = True) -> dict:
    """Create complete ecommerce tracking setup in GTM (실제 GTM에 생성)"""
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
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
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
                        result = loop.run_until_complete(client.create_variable(
                            account_id, container_id,
                            component['name'], component['type'],
                            component.get('parameters', {})
                        ))
                    elif component_type == "trigger":
                        result = loop.run_until_complete(client.create_trigger(
                            account_id, container_id,
                            component['name'], component['type'],
                            component.get('filters', [])
                        ))
                    elif component_type == "tag":
                        result = loop.run_until_complete(client.create_tag(
                            account_id, container_id,
                            component['name'], component['type'],
                            component.get('parameters', {})
                        ))
                    
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
        
        loop.close()
        return results
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create ecommerce setup: {str(e)}"
        }

@mcp.tool()
def publish_gtm_container(account_id: str, container_id: str, version_name: str, version_notes: str = "Published via MCP") -> dict:
    """Publish GTM container version (실제 배포)"""
    try:
        client = get_gtm_client()
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(client.publish_version(account_id, container_id, version_name, version_notes))
        loop.close()
        
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
def generate_ga4_template(measurement_id: str, config_parameters: dict = None) -> dict:
    """Generate GA4 tag template (JSON only)"""
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

# Run the MCP server
if __name__ == '__main__':
    logger.info("Starting FastMCP GTM Server...")
    mcp.run()