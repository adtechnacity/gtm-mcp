"""Tests for the get_gtm_variable tool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import tool_error


def _make_mock_variable_client(variable: dict):
    """Build a mock client whose variables().get() returns `variable`."""
    client = MagicMock()
    variables = client.service.accounts().containers().workspaces().variables()
    get_req = MagicMock()
    get_req.execute = MagicMock(return_value=dict(variable))
    variables.get = MagicMock(return_value=get_req)
    return client, variables


class TestGetGtmVariable:
    @pytest.mark.asyncio
    async def test_returns_full_variable_resource(self):
        from gtm_mcp.read_tools import get_gtm_variable

        variable = {
            "name": "domain",
            "variableId": "15",
            "type": "jsm",
            "parameter": [{"key": "javascript", "value": "function() { return 'x'; }",
                           "type": "template"}],
            "fingerprint": "fp",
        }
        client, variables = _make_mock_variable_client(variable)

        with patch("gtm_mcp.read_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.read_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", "accounts/1/containers/2/workspaces/54"))):
            result = await get_gtm_variable(
                account_id="1", container_id="2", variable_id="15", workspace_id="54"
            )

        assert result["status"] == "success"
        assert result["variable"]["name"] == "domain"
        assert result["variable"]["variableId"] == "15"
        assert result["variable"]["parameter"][0]["key"] == "javascript"

        get_call = variables.get.call_args
        assert get_call.kwargs["path"] == "accounts/1/containers/2/workspaces/54/variables/15"

    @pytest.mark.asyncio
    async def test_invalid_variable_id_returns_error(self):
        from gtm_mcp.read_tools import get_gtm_variable

        message = await tool_error(get_gtm_variable(
            account_id="1", container_id="2", variable_id="bad"
        ))
        assert "variable_id" in message
