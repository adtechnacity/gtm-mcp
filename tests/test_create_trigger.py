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


def _make_mock_trigger_client(created_id: str = "999"):
    """Build a MagicMock GTM client whose triggers().create(parent, body)
    echoes the body back with triggerId + path populated."""
    client = MagicMock()
    triggers = client.service.accounts().containers().workspaces().triggers()

    def _create(parent, body):
        result_body = dict(body)
        result_body["triggerId"] = created_id
        result_body["path"] = f"{parent}/triggers/{created_id}"
        create_req = MagicMock()
        create_req.execute = MagicMock(return_value=result_body)
        return create_req

    triggers.create = MagicMock(side_effect=_create)
    return client, triggers


class TestCreateTriggerBackCompat:
    @pytest.mark.asyncio
    async def test_event_name_only_builds_customevent_body(self):
        """Old-style call (event_name only, no trigger_type) must produce
        the same body shape today's create_trigger produced."""
        from fastmcp_gtm_write_tools import create_trigger

        client, triggers = _make_mock_trigger_client(created_id="500")

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await create_trigger(
                account_id="1", container_id="2",
                trigger_name="CE - consent_update",
                event_name="consent_update",
            )

        assert result["status"] == "success"
        assert result["trigger_id"] == "500"
        assert result["trigger_name"] == "CE - consent_update"
        assert result["trigger_type"] == "customEvent"

        body = triggers.create.call_args.kwargs["body"]
        assert body == {
            "name": "CE - consent_update",
            "type": "customEvent",
            "customEventFilter": [
                {
                    "type": "equals",
                    "parameter": [
                        {"key": "arg0", "value": "{{_event}}", "type": "template"},
                        {"key": "arg1", "value": "consent_update", "type": "template"},
                    ],
                }
            ],
        }


class TestCreateTriggerLinkClick:
    @pytest.mark.asyncio
    async def test_linkclick_with_three_filters_builds_filter_list(self):
        """Mirror trigger 77's structure: linkClick with a filter list and
        no customEventFilter."""
        from fastmcp_gtm_write_tools import create_trigger

        client, triggers = _make_mock_trigger_client(created_id="600")

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", "accounts/1/containers/2/workspaces/54"))):
            result = await create_trigger(
                account_id="1", container_id="2", workspace_id="54",
                trigger_name="Chrome Mobile Click Outs - /ma/ Enabled",
                trigger_type="linkClick",
                filters=[
                    {"variable": "dl_browser", "operator": "equals",
                     "value": "Chrome"},
                    {"variable": "Page URL", "operator": "contains",
                     "value": "/ma/"},
                    {"variable": "VENDOR_G_ADS_CONVERSION_ID",
                     "operator": "equals", "value": "null", "negate": True},
                ],
            )

        assert result["status"] == "success"
        assert result["trigger_id"] == "600"
        assert result["trigger_type"] == "linkClick"

        body = triggers.create.call_args.kwargs["body"]
        assert body["name"] == "Chrome Mobile Click Outs - /ma/ Enabled"
        assert body["type"] == "linkClick"
        assert "customEventFilter" not in body
        assert body["filter"] == [
            {
                "type": "equals",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{dl_browser}}"},
                    {"type": "template", "key": "arg1", "value": "Chrome"},
                ],
            },
            {
                "type": "contains",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{Page URL}}"},
                    {"type": "template", "key": "arg1", "value": "/ma/"},
                ],
            },
            {
                "type": "equals",
                "parameter": [
                    {"type": "template", "key": "arg0",
                     "value": "{{VENDOR_G_ADS_CONVERSION_ID}}"},
                    {"type": "template", "key": "arg1", "value": "null"},
                    {"type": "boolean", "key": "negate", "value": "true"},
                ],
            },
        ]

    @pytest.mark.asyncio
    async def test_customevent_with_extra_filters_keeps_both_sections(self):
        """customEvent with filters= adds a filter section in addition to
        the customEventFilter that matches the event name."""
        from fastmcp_gtm_write_tools import create_trigger

        client, triggers = _make_mock_trigger_client()

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await create_trigger(
                account_id="1", container_id="2",
                trigger_name="CE with filter",
                event_name="my_event",
                filters=[{"variable": "Page URL", "operator": "contains", "value": "/x/"}],
            )

        assert result["status"] == "success"
        body = triggers.create.call_args.kwargs["body"]
        assert body["type"] == "customEvent"
        # event-name match still present
        assert body["customEventFilter"][0]["parameter"][0]["value"] == "{{_event}}"
        assert body["customEventFilter"][0]["parameter"][1]["value"] == "my_event"
        # extra filter present
        assert body["filter"] == [
            {
                "type": "contains",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{Page URL}}"},
                    {"type": "template", "key": "arg1", "value": "/x/"},
                ],
            }
        ]


class TestCreateTriggerValidation:
    @pytest.mark.asyncio
    async def test_unsupported_trigger_type_returns_error(self):
        from fastmcp_gtm_write_tools import create_trigger

        result = await create_trigger(
            account_id="1", container_id="2",
            trigger_name="X", trigger_type="scrollDepth",
            filters=[{"variable": "v", "operator": "equals", "value": "x"}],
        )
        assert result["status"] == "error"
        assert "scrollDepth" in result["message"]
        assert "supported" in result["message"]

    @pytest.mark.asyncio
    async def test_customevent_with_neither_event_name_nor_filters_returns_error(self):
        from fastmcp_gtm_write_tools import create_trigger

        result = await create_trigger(
            account_id="1", container_id="2", trigger_name="X",
        )
        assert result["status"] == "error"
        assert "customEvent" in result["message"]
        assert "event_name" in result["message"]
        assert "filters" in result["message"]

    @pytest.mark.asyncio
    async def test_linkclick_with_no_filters_returns_error(self):
        from fastmcp_gtm_write_tools import create_trigger

        result = await create_trigger(
            account_id="1", container_id="2",
            trigger_name="X", trigger_type="linkClick",
        )
        assert result["status"] == "error"
        assert "linkClick" in result["message"]
        assert "filters" in result["message"]

    @pytest.mark.asyncio
    async def test_linkclick_with_empty_filters_returns_error(self):
        from fastmcp_gtm_write_tools import create_trigger

        result = await create_trigger(
            account_id="1", container_id="2",
            trigger_name="X", trigger_type="linkClick", filters=[],
        )
        assert result["status"] == "error"
        assert "filters" in result["message"]

    @pytest.mark.asyncio
    async def test_bad_operator_in_filter_returns_error(self):
        from fastmcp_gtm_write_tools import create_trigger

        client, triggers = _make_mock_trigger_client()
        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await create_trigger(
                account_id="1", container_id="2",
                trigger_name="X", trigger_type="linkClick",
                filters=[{"variable": "v", "operator": "lessThan", "value": "5"}],
            )
        assert result["status"] == "error"
        assert "operator" in result["message"]
        # The error from _dsl_to_gtm_filter should be surfaced via the
        # caught-exception path; make sure no trigger was actually created.
        triggers.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_account_id_returns_error(self):
        from fastmcp_gtm_write_tools import create_trigger

        result = await create_trigger(
            account_id="bad", container_id="2",
            trigger_name="X", event_name="e",
        )
        assert result["status"] == "error"
        assert "account_id" in result["message"]
