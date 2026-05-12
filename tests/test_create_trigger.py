"""Tests for _dsl_to_gtm_filter helper and generalized create_trigger tool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDslToGtmFilter:
    def test_equals_basic(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        out = _dsl_to_gtm_filter(
            {"variable": "dl_browser", "operator": "equals", "value": "Chrome"}
        )
        assert out == {
            "type": "equals",
            "parameter": [
                {"type": "template", "key": "arg0", "value": "{{dl_browser}}"},
                {"type": "template", "key": "arg1", "value": "Chrome"},
            ],
        }

    def test_contains_with_negate(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        out = _dsl_to_gtm_filter(
            {"variable": "Page URL", "operator": "contains",
             "value": "/m/", "negate": True}
        )
        assert out == {
            "type": "contains",
            "parameter": [
                {"type": "template", "key": "arg0", "value": "{{Page URL}}"},
                {"type": "template", "key": "arg1", "value": "/m/"},
                {"type": "boolean", "key": "negate", "value": "true"},
            ],
        }

    def test_already_wrapped_variable_is_not_double_wrapped(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        out = _dsl_to_gtm_filter(
            {"variable": "{{dl_browser}}", "operator": "equals", "value": "Safari"}
        )
        assert out["parameter"][0]["value"] == "{{dl_browser}}"

    def test_value_is_stringified(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        out = _dsl_to_gtm_filter(
            {"variable": "count", "operator": "equals", "value": 3}
        )
        assert out["parameter"][1]["value"] == "3"

    @pytest.mark.parametrize("op", ["equals", "contains", "startsWith", "endsWith", "matchRegex"])
    def test_all_supported_operators_pass_through_as_type(self, op):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        out = _dsl_to_gtm_filter({"variable": "v", "operator": op, "value": "x"})
        assert out["type"] == op

    def test_missing_variable_raises(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        with pytest.raises(ValueError, match="variable"):
            _dsl_to_gtm_filter({"operator": "equals", "value": "x"})

    def test_missing_operator_raises(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        with pytest.raises(ValueError, match="operator"):
            _dsl_to_gtm_filter({"variable": "v", "value": "x"})

    def test_missing_value_raises(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        with pytest.raises(ValueError, match="value"):
            _dsl_to_gtm_filter({"variable": "v", "operator": "equals"})

    def test_unsupported_operator_raises(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        with pytest.raises(ValueError, match="operator"):
            _dsl_to_gtm_filter({"variable": "v", "operator": "lessThan", "value": "5"})

    def test_value_none_raises(self):
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter
        with pytest.raises(ValueError, match="value"):
            _dsl_to_gtm_filter({"variable": "v", "operator": "equals", "value": None})

    def test_value_falsy_but_not_none_is_stringified(self):
        """Pin behavior: 0, False, and '' are valid values; only None is rejected."""
        from fastmcp_gtm_helpers import _dsl_to_gtm_filter

        out_zero = _dsl_to_gtm_filter(
            {"variable": "v", "operator": "equals", "value": 0}
        )
        assert out_zero["parameter"][1]["value"] == "0"

        out_empty = _dsl_to_gtm_filter(
            {"variable": "v", "operator": "equals", "value": ""}
        )
        assert out_empty["parameter"][1]["value"] == ""
