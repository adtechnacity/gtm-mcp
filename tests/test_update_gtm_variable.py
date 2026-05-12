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
        from fastmcp_gtm_write_tools import update_gtm_variable

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

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
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
