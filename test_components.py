"""Tests for gtm_components — regression tests for template correctness."""
import pytest

from gtm_components import GTMComponentTemplates, GTMWorkflowBuilder


class TestCustomEventTrigger:
    """Regression test for {{_event}} fix (was {{Event}})."""

    def test_uses_correct_event_variable(self):
        trigger = GTMComponentTemplates.custom_event_trigger("purchase")
        filters = trigger["filters"]
        arg0 = filters[0]["parameter"][0]
        assert arg0["value"] == "{{_event}}", (
            "Must use {{_event}} (GTM built-in), not {{Event}}"
        )

    def test_event_name_in_filter(self):
        trigger = GTMComponentTemplates.custom_event_trigger("add_to_cart")
        arg1 = trigger["filters"][0]["parameter"][1]
        assert arg1["value"] == "add_to_cart"

    def test_trigger_name_includes_event(self):
        trigger = GTMComponentTemplates.custom_event_trigger("purchase")
        assert "purchase" in trigger["name"]

    def test_trigger_type_is_custom_event(self):
        trigger = GTMComponentTemplates.custom_event_trigger("test")
        assert trigger["type"] == "customEvent"


class TestGA4Tag:
    def test_measurement_id_in_parameters(self):
        tag = GTMComponentTemplates.google_analytics_4_tag("G-TEST123")
        assert tag["parameters"]["measurementId"] == "G-TEST123"

    def test_tag_type(self):
        tag = GTMComponentTemplates.google_analytics_4_tag("G-TEST123")
        assert tag["type"] == "gtagjs"


class TestWorkflowBuilder:
    def test_get_components_returns_all_keys(self):
        builder = GTMWorkflowBuilder()
        builder.add_google_analytics_4_setup("G-TEST")
        components = builder.get_components()
        assert "tags" in components
        assert "triggers" in components
        assert "variables" in components

    def test_fresh_builder_has_empty_components(self):
        builder = GTMWorkflowBuilder()
        components = builder.get_components()
        assert components["tags"] == []
        assert components["triggers"] == []
        assert components["variables"] == []
