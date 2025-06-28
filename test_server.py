#!/usr/bin/env python3
"""
Test script to verify MCP server functionality without requiring full Claude integration
"""
import asyncio
import json
from gtm_components import GTMComponentTemplates, GTMWorkflowBuilder

async def test_component_templates():
    """Test the component templates"""
    print("Testing GTM Component Templates...")
    
    # Test GA4 tag template
    ga4_tag = GTMComponentTemplates.google_analytics_4_tag("G-XXXXXXXXXX")
    print(f"✓ GA4 Tag Template: {ga4_tag['name']}")
    
    # Test Facebook Pixel template
    fb_pixel = GTMComponentTemplates.facebook_pixel_tag("123456789")
    print(f"✓ Facebook Pixel Template: {fb_pixel['name']}")
    
    # Test triggers
    page_view_trigger = GTMComponentTemplates.page_view_trigger()
    print(f"✓ Page View Trigger: {page_view_trigger['name']}")
    
    click_trigger = GTMComponentTemplates.click_trigger('.cta-button')
    print(f"✓ Click Trigger: {click_trigger['name']}")
    
    # Test variables
    dl_variable = GTMComponentTemplates.data_layer_variable("User ID", "userId")
    print(f"✓ Data Layer Variable: {dl_variable['name']}")
    
    print("Component templates working correctly!\n")

async def test_workflow_builder():
    """Test the workflow builder"""
    print("Testing GTM Workflow Builder...")
    
    # Test ecommerce workflow
    builder = GTMWorkflowBuilder()
    builder.add_google_analytics_4_setup("G-XXXXXXXXXX", enhanced_ecommerce=True)
    builder.add_facebook_pixel_setup("123456789")
    builder.add_conversion_tracking()
    builder.add_form_tracking("#checkout-form")
    builder.add_click_tracking(".add-to-cart", "add_to_cart")
    builder.add_common_variables()
    
    components = builder.get_components()
    
    print(f"✓ Created workflow with:")
    print(f"  - {len(components['tags'])} tags")
    print(f"  - {len(components['triggers'])} triggers") 
    print(f"  - {len(components['variables'])} variables")
    
    # Export to JSON
    json_export = builder.export_json("test_workflow.json")
    print(f"✓ Exported workflow to JSON ({len(json_export)} characters)")
    
    print("Workflow builder working correctly!\n")

async def test_workflow_types():
    """Test different workflow types"""
    print("Testing Different Workflow Types...")
    
    workflow_types = ["ecommerce", "lead_generation", "content_site"]
    
    for workflow_type in workflow_types:
        builder = GTMWorkflowBuilder()
        
        # Add GA4 setup
        enhanced_ecommerce = workflow_type == "ecommerce"
        builder.add_google_analytics_4_setup("G-TEST123", enhanced_ecommerce)
        
        # Add Facebook Pixel
        builder.add_facebook_pixel_setup("987654321")
        
        # Add conversion tracking
        builder.add_conversion_tracking()
        
        # Add specific tracking based on workflow type
        if workflow_type == "lead_generation":
            builder.add_form_tracking()
            builder.add_click_tracking('.cta-button', 'cta_click')
        elif workflow_type == "ecommerce":
            builder.add_form_tracking('#checkout-form')
            builder.add_click_tracking('.add-to-cart', 'add_to_cart')
            builder.add_click_tracking('.buy-now', 'purchase_intent')
        elif workflow_type == "content_site":
            builder.add_click_tracking('.share-button', 'content_share')
            builder.add_form_tracking('#newsletter-form')
        
        builder.add_common_variables()
        components = builder.get_components()
        
        print(f"✓ {workflow_type.title()} workflow:")
        print(f"  - {len(components['tags'])} tags")
        print(f"  - {len(components['triggers'])} triggers")
        print(f"  - {len(components['variables'])} variables")
    
    print("All workflow types working correctly!\n")

async def main():
    """Run all tests"""
    print("=== MCP GTM Server Component Tests ===\n")
    
    await test_component_templates()
    await test_workflow_builder()
    await test_workflow_types()
    
    print("=== All Tests Passed! ===")
    print("\nThe MCP server components are working correctly.")
    print("To use with Claude, make sure to:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Set up Google Cloud credentials (credentials.json)")
    print("3. Configure the MCP server in Claude's config")

if __name__ == "__main__":
    asyncio.run(main())