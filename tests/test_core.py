"""Error contract, per-thread transport, workspace resolution, publish."""
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import google_auth_httplib2
import httplib2
import pytest
from googleapiclient.errors import HttpError
from mcp.shared.memory import create_connected_server_and_client_session

from conftest import tool_error
from gtm_mcp import helpers
from gtm_mcp.helpers import (
    _execute, _forget_workspace, _pick_workspace, _resolve_workspace_id, gtm_tool,
)
from gtm_mcp.server import mcp


def _http_error(status, message):
    return HttpError(httplib2.Response({"status": status}),
                     json.dumps({"error": {"message": message}}).encode())


# ---------------------------------------------------------------------------
# gtm_tool error contract
# ---------------------------------------------------------------------------

@pytest.fixture
def probe():
    """A throwaway tool, unregistered afterwards so it never leaks into tools/list."""
    @gtm_tool("Failed to probe")
    async def _probe_tool(mode: str, count: int = 1) -> dict:
        """Test-only tool."""
        if mode == "raise":
            raise _http_error(404, "Not found or permission denied.")
        if mode == "boom":
            raise RuntimeError("socket closed")
        return {"status": mode, "message": f"{mode} message"}

    yield _probe_tool
    mcp._tool_manager._tools.pop("_probe_tool", None)


class TestGtmTool:
    @pytest.mark.asyncio
    async def test_success_and_partial_pass_through(self, probe):
        assert (await probe("success"))["status"] == "success"
        assert (await probe("partial"))["status"] == "partial"

    @pytest.mark.asyncio
    async def test_error_dict_becomes_tool_error(self, probe):
        assert await tool_error(probe("error")) == "error message"

    @pytest.mark.asyncio
    async def test_http_error_is_summarized(self, probe):
        message = await tool_error(probe("raise"))
        assert message == "Failed to probe: HTTP 404: Not found or permission denied."

    @pytest.mark.asyncio
    async def test_other_exceptions_keep_their_text(self, probe):
        assert await tool_error(probe("boom")) == "Failed to probe: socket closed"

    @pytest.mark.asyncio
    async def test_schema_comes_from_wrapped_signature(self, probe):
        tool = mcp._tool_manager.get_tool("_probe_tool")
        assert set(tool.parameters["properties"]) == {"mode", "count"}
        assert tool.parameters["required"] == ["mode"]

    @pytest.mark.asyncio
    async def test_client_sees_is_error(self):
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            failed = await client.call_tool("pause_tag", {
                "account_id": "bad", "container_id": "2", "tag_id": "1"})
        assert failed.isError
        assert "account_id" in failed.content[0].text


# ---------------------------------------------------------------------------
# Per-thread transport
# ---------------------------------------------------------------------------

class TestExecute:
    def _request(self, creds):
        req = MagicMock()
        req.http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http())
        req.execute = MagicMock(return_value={"ok": True})
        return req

    def test_each_thread_gets_its_own_connection(self):
        creds = MagicMock()
        seen = []

        def worker():
            req = self._request(creds)
            _execute(req)
            _execute(req)
            seen.append([c.kwargs["http"] for c in req.execute.call_args_list])

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        (a1, a2), (b1, b2) = seen
        assert a1 is a2 and b1 is b2          # reused within a thread
        assert a1 is not b1                   # never shared across threads
        assert a1.credentials is creds        # same credentials

    def test_new_credentials_get_a_new_connection(self):
        first, second = self._request(MagicMock()), self._request(MagicMock())
        _execute(first)
        _execute(second)
        assert first.execute.call_args.kwargs["http"] is not second.execute.call_args.kwargs["http"]

    def test_non_authorized_http_executes_as_is(self):
        req = MagicMock()
        _execute(req)
        req.execute.assert_called_once_with()


class TestQuotaRetry:
    def _request(self, *outcomes):
        req = MagicMock()
        req.execute.side_effect = list(outcomes)
        return req

    def test_retries_429_then_succeeds(self):
        req = self._request(_http_error(429, "Quota exceeded"), {"ok": True})
        with patch("gtm_mcp.helpers.time.sleep") as sleep:
            assert _execute(req) == {"ok": True}
        assert sleep.call_count == 1
        assert sleep.call_args.args[0] >= helpers._RETRY_DELAYS[0]

    def test_gives_up_after_all_delays(self):
        errors = [_http_error(429, "Quota exceeded")] * (len(helpers._RETRY_DELAYS) + 1)
        req = self._request(*errors)
        with patch("gtm_mcp.helpers.time.sleep") as sleep, pytest.raises(HttpError):
            _execute(req)
        assert sleep.call_count == len(helpers._RETRY_DELAYS)

    @pytest.mark.parametrize("status", [404, 500, 503])
    def test_other_errors_are_not_retried(self, status):
        req = self._request(_http_error(status, "nope"), {"ok": True})
        with patch("gtm_mcp.helpers.time.sleep") as sleep, pytest.raises(HttpError):
            _execute(req)
        sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------

def _ws(ws_id, name):
    return {"workspaceId": ws_id, "name": name}


class TestPickWorkspace:
    def test_prefers_default_workspace_by_name(self):
        assert _pick_workspace([_ws("7", "Kem draft"), _ws("54", "Default Workspace")], "2") == "54"

    def test_single_workspace_is_unambiguous(self):
        assert _pick_workspace([_ws("12", "Only one")], "2") == "12"

    def test_ambiguous_raises_with_listing(self):
        with pytest.raises(ValueError, match="pass workspace_id explicitly.*7='A'.*8='B'"):
            _pick_workspace([_ws("7", "A"), _ws("8", "B")], "2")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="no workspaces"):
            _pick_workspace([], "2")

    def test_legacy_one_kept_when_it_exists(self):
        workspaces = [_ws("1", "Old"), _ws("54", "Default Workspace")]
        assert _pick_workspace(workspaces, "2", prefer_id_1=True) == "1"
        assert _pick_workspace(workspaces, "2") == "54"


class TestResolveWorkspaceId:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        helpers._workspace_cache.clear()
        yield
        helpers._workspace_cache.clear()

    def _client(self, *responses):
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        ws.list.side_effect = [MagicMock(execute=MagicMock(return_value=r)) for r in responses]
        return client, ws

    @pytest.mark.asyncio
    async def test_explicit_id_skips_api(self):
        client, ws = self._client()
        assert await _resolve_workspace_id(client, "1", "2", "77") == "77"
        ws.list.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_id_must_be_numeric(self):
        client, _ = self._client()
        with pytest.raises(ValueError, match="workspace_id"):
            await _resolve_workspace_id(client, "1", "2", "abc")

    @pytest.mark.asyncio
    async def test_cached_until_forgotten(self):
        client, ws = self._client(
            {"workspace": [_ws("54", "Default Workspace")]},
            {"workspace": [_ws("55", "Default Workspace")]},
        )
        assert await _resolve_workspace_id(client, "1", "2", None) == "54"
        assert await _resolve_workspace_id(client, "1", "2", None) == "54"
        assert ws.list.call_count == 1
        _forget_workspace("1", "2")
        assert await _resolve_workspace_id(client, "1", "2", None) == "55"

    @pytest.mark.asyncio
    async def test_cache_expires(self):
        client, ws = self._client(
            {"workspace": [_ws("54", "Default Workspace")]},
            {"workspace": [_ws("55", "Default Workspace")]},
        )
        assert await _resolve_workspace_id(client, "1", "2", None) == "54"
        ws_id, resolved_at = helpers._workspace_cache[("1", "2")]
        helpers._workspace_cache[("1", "2")] = (ws_id, resolved_at - helpers._WORKSPACE_CACHE_TTL - 1)
        assert await _resolve_workspace_id(client, "1", "2", None) == "55"


# ---------------------------------------------------------------------------
# publish_gtm_container
# ---------------------------------------------------------------------------

class TestPublish:
    def _client(self, create_version_result):
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        ws.create_version.return_value.execute.return_value = create_version_result
        versions = client.service.accounts().containers().versions()
        versions.publish.return_value.execute.return_value = {
            "containerVersion": {"containerVersionId": "88", "path": "v/88"}}
        return client, versions

    async def _publish(self, client):
        from gtm_mcp.lifecycle_tools import publish_gtm_container
        with patch("gtm_mcp.lifecycle_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.lifecycle_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", "accounts/1/containers/2/workspaces/54"))), \
             patch("gtm_mcp.lifecycle_tools._forget_workspace") as forget:
            return await publish_gtm_container("1", "2", "v88"), forget

    @pytest.mark.asyncio
    async def test_publishes_and_forgets_workspace(self):
        client, versions = self._client({"containerVersion": {"path": "v/88"}})
        result, forget = await self._publish(client)
        assert result["version_id"] == "88"
        versions.publish.assert_called_once_with(path="v/88")
        forget.assert_called_once_with("1", "2")

    @pytest.mark.asyncio
    async def test_compiler_error_is_reported_and_nothing_published(self):
        client, versions = self._client({"compilerError": True})
        message = await tool_error(self._publish(client))
        assert "compilerError" in message
        versions.publish.assert_not_called()
