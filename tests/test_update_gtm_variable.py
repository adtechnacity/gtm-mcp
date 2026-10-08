"""Tests for update_gtm_variable tool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_client(variable: dict):
    """Build a MagicMock GTM client whose variables().get() returns `variable`
    and whose variables().update() echoes back the body that was sent.

    Returns (client, variables_mock) — variables_mock is the leaf MagicMock
    so tests can inspect call_args on .get / .update.
    """
    client = MagicMock()
    variables = client.service.accounts().containers().workspaces().variables()

    get_req = MagicMock()
    get_req.execute = MagicMock(return_value=dict(variable))
    variables.get = MagicMock(return_value=get_req)

    def _update(path, body, fingerprint):
        update_req = MagicMock()
        update_req.execute = MagicMock(return_value=dict(body))
        return update_req

    variables.update = MagicMock(side_effect=_update)
    return client, variables


class TestUpdateGtmVariableJavascriptShortcut:
    @pytest.mark.asyncio
    async def test_jsm_javascript_shortcut_replaces_parameter_list(self):
        from gtm_mcp.write_tools import update_gtm_variable

        variable = {
            "name": "isOOPage",
            "variableId": "425",
            "type": "jsm",
            "fingerprint": "fp1",
            "parameter": [
                {"type": "template", "key": "javascript",
                 "value": "function() { return false; }"}
            ],
        }
        client, variables = _make_mock_client(variable)

        new_source = "function() {\n  return {{Page Path}}.indexOf('-oocta') !== -1;\n}"

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", "accounts/1/containers/2/workspaces/54"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="425",
                workspace_id="54", javascript=new_source,
            )

        assert result["status"] == "success"
        assert result["variable_id"] == "425"
        assert result["variable_name"] == "isOOPage"
        assert result["variable_type"] == "jsm"
        assert result["updated_fields"] == ["parameters"]

        # The update call must have been made with fingerprint and the new param list.
        variables.update.assert_called_once()
        call = variables.update.call_args
        assert call.kwargs["path"] == "accounts/1/containers/2/workspaces/54/variables/425"
        assert call.kwargs["fingerprint"] == "fp1"
        assert call.kwargs["body"]["parameter"] == [
            {"type": "template", "key": "javascript", "value": new_source}
        ]


class TestUpdateGtmVariableOtherFields:
    @pytest.mark.asyncio
    async def test_raw_parameters_update_replaces_parameter_list(self):
        from gtm_mcp.write_tools import update_gtm_variable

        variable = {
            "name": "MY_VAR", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": [
                {"type": "template", "key": "value", "value": "old"}
            ],
        }
        client, variables = _make_mock_client(variable)
        new_params = [{"type": "template", "key": "value", "value": "new"}]

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                parameters=new_params,
            )

        assert result["status"] == "success"
        assert result["updated_fields"] == ["parameters"]
        assert variables.update.call_args.kwargs["body"]["parameter"] == new_params

    @pytest.mark.asyncio
    async def test_name_only_update_leaves_parameter_list_intact(self):
        from gtm_mcp.write_tools import update_gtm_variable

        original_params = [{"type": "template", "key": "value", "value": "x"}]
        variable = {
            "name": "OLD_NAME", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": original_params,
        }
        client, variables = _make_mock_client(variable)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                name="NEW_NAME",
            )

        assert result["status"] == "success"
        assert result["updated_fields"] == ["name"]
        body = variables.update.call_args.kwargs["body"]
        assert body["name"] == "NEW_NAME"
        assert body["parameter"] == original_params

    @pytest.mark.asyncio
    async def test_combined_name_and_notes_update(self):
        from gtm_mcp.write_tools import update_gtm_variable

        variable = {
            "name": "V", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": [],
        }
        client, variables = _make_mock_client(variable)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                name="V2", notes="ticket-1234",
            )

        assert result["status"] == "success"
        assert set(result["updated_fields"]) == {"name", "notes"}
        body = variables.update.call_args.kwargs["body"]
        assert body["name"] == "V2"
        assert body["notes"] == "ticket-1234"

    @pytest.mark.asyncio
    async def test_parent_folder_id_update(self):
        from gtm_mcp.write_tools import update_gtm_variable

        variable = {
            "name": "V", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": [], "parentFolderId": "100",
        }
        client, variables = _make_mock_client(variable)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                parent_folder_id="200",
            )

        assert result["status"] == "success"
        assert result["updated_fields"] == ["parent_folder_id"]
        assert variables.update.call_args.kwargs["body"]["parentFolderId"] == "200"


class TestUpdateGtmVariableValidation:
    @pytest.mark.asyncio
    async def test_empty_variable_id_returns_error(self):
        from gtm_mcp.write_tools import update_gtm_variable

        result = await update_gtm_variable(
            account_id="1", container_id="2", variable_id="",
            javascript="function() {}",
        )
        assert result["status"] == "error"
        assert "variable_id" in result["message"]

    @pytest.mark.asyncio
    async def test_nothing_to_update_returns_error(self):
        from gtm_mcp.write_tools import update_gtm_variable

        # All optional fields omitted. Must not call .get() or .update().
        variable = {"name": "V", "variableId": "10", "type": "c",
                    "fingerprint": "fp", "parameter": []}
        client, variables = _make_mock_client(variable)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
            )

        assert result["status"] == "error"
        assert "nothing to update" in result["message"].lower()
        variables.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_parameters_and_javascript_both_set_returns_error(self):
        from gtm_mcp.write_tools import update_gtm_variable

        result = await update_gtm_variable(
            account_id="1", container_id="2", variable_id="10",
            parameters=[{"type": "template", "key": "value", "value": "x"}],
            javascript="function() {}",
        )
        assert result["status"] == "error"
        assert "mutually exclusive" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_javascript_on_non_jsm_variable_returns_error(self):
        from gtm_mcp.write_tools import update_gtm_variable

        # Variable type is "v" (Data Layer Variable), not "jsm".
        variable = {"name": "DLV", "variableId": "10", "type": "v",
                    "fingerprint": "fp", "parameter": []}
        client, variables = _make_mock_client(variable)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                javascript="function() {}",
            )

        assert result["status"] == "error"
        assert "jsm" in result["message"]
        assert "'v'" in result["message"]
        variables.update.assert_not_called()
