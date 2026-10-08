"""Tests for create_gtm_variable tool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

WS_PARENT = "accounts/1/containers/2/workspaces/54"


def _make_mock_client():
    """MagicMock GTM client whose variables().create() echoes the body back
    with a variableId. Returns (client, variables_mock)."""
    client = MagicMock()
    variables = client.service.accounts().containers().workspaces().variables()

    def _create(parent, body):
        req = MagicMock()
        req.execute = MagicMock(return_value={**body, "variableId": "900",
                                              "path": f"{parent}/variables/900"})
        return req

    variables.create = MagicMock(side_effect=_create)
    return client, variables


async def _call(**kwargs):
    from gtm_mcp.write_tools import create_gtm_variable

    client, variables = _make_mock_client()
    with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
         patch("gtm_mcp.write_tools._resolve_workspace_parent",
               new=AsyncMock(return_value=("54", WS_PARENT))):
        result = await create_gtm_variable(account_id="1", container_id="2",
                                           workspace_id="54", **kwargs)
    return result, variables


class TestCreateGtmVariable:
    @pytest.mark.asyncio
    async def test_javascript_shortcut_creates_jsm_variable(self):
        src = "function() { return 'dark'; }"
        result, variables = await _call(name="color_scheme", javascript=src)

        assert result["status"] == "success"
        assert result["variable_id"] == "900"
        assert result["variable_type"] == "jsm"
        call = variables.create.call_args
        assert call.kwargs["parent"] == WS_PARENT
        assert call.kwargs["body"] == {
            "name": "color_scheme",
            "type": "jsm",
            "parameter": [{"type": "template", "key": "javascript", "value": src}],
        }

    @pytest.mark.asyncio
    async def test_raw_type_and_parameters(self):
        params = [{"type": "template", "key": "value", "value": "abc"}]
        result, variables = await _call(name="CONST", variable_type="c",
                                        parameters=params, notes="n",
                                        parent_folder_id="352")

        assert result["status"] == "success"
        body = variables.create.call_args.kwargs["body"]
        assert body == {"name": "CONST", "type": "c", "parameter": params,
                        "notes": "n", "parentFolderId": "352"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kwargs,fragment", [
        ({"name": "x", "javascript": "f", "parameters": []}, "mutually exclusive"),
        ({"name": "x", "javascript": "f", "variable_type": "c"}, "jsm"),
        ({"name": "x", "parameters": []}, "variable_type"),
        ({"name": "", "javascript": "f"}, "name"),
    ])
    async def test_invalid_input_never_calls_api(self, kwargs, fragment):
        result, variables = await _call(**kwargs)

        assert result["status"] == "error"
        assert fragment in result["message"]
        variables.create.assert_not_called()
