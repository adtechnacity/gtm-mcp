# `update_gtm_variable` + generalized `create_trigger` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-place `update_gtm_variable` tool (with a `javascript=` shortcut for jsm variables) and generalize the existing `create_trigger` so it accepts arbitrary trigger types plus a friendly filter DSL, while preserving backward compatibility for today's customEvent callers.

**Architecture:** A new `_dsl_to_gtm_filter` helper in `fastmcp_gtm_helpers.py` converts ergonomic dict entries to GTM's verbose filter shape. `update_gtm_variable` mirrors `update_tag_consent_settings`: GET → mutate-only-passed-fields → UPDATE with `fingerprint`. `create_trigger` is rewritten in place to dispatch on `trigger_type` — the customEvent branch produces a body structurally equal to today's, the other branches build `{name, type, filter}` from DSL-converted filters.

**Tech Stack:** Python 3, FastMCP, `googleapiclient` (Tag Manager API v2), `pytest` + `pytest-asyncio`, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-05-12-variable-and-trigger-tools-design.md`

---

## File Structure

- **Modify** `fastmcp_gtm_helpers.py` — add `_dsl_to_gtm_filter` (and two small constant sets `SUPPORTED_DSL_OPERATORS`, `SUPPORTED_TRIGGER_TYPES`) used by `create_trigger`.
- **Modify** `fastmcp_gtm_write_tools.py` — import the new helper + constants; add `update_gtm_variable` tool; rewrite the body of `create_trigger`; bump module docstring count 11 → 12.
- **Create** `tests/test_update_gtm_variable.py` — pytest-asyncio tests for the new tool.
- **Create** `tests/test_create_trigger.py` — pytest-asyncio tests for DSL helper + generalized trigger creation + back-compat.
- **Modify** `README.md` — bump "21 MCP tools" to 22, add `update_gtm_variable` line, update `create_trigger` description.
- **Modify** `AGENTS.md` — match README updates.

No other files change. Existing helpers (`_validate_ids`, `_resolve_workspace_parent`, `_run`, `get_gtm_client`, the shared `mcp` instance) are reused as-is.

---

## Task 1: `_dsl_to_gtm_filter` helper

**Files:**
- Create: `tests/test_create_trigger.py`
- Modify: `fastmcp_gtm_helpers.py` (append after `_build_consent_settings`, around line 181)

- [ ] **Step 1: Create the test file with the first failing helper-unit-test class**

Write to `tests/test_create_trigger.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_create_trigger.py::TestDslToGtmFilter -v`
Expected: FAIL — `ImportError: cannot import name '_dsl_to_gtm_filter' from 'fastmcp_gtm_helpers'`.

- [ ] **Step 3: Add the helper and supporting constants to `fastmcp_gtm_helpers.py`**

In `fastmcp_gtm_helpers.py`, append after `_build_consent_settings` (currently ends around line 181):

```python


# ---------------------------------------------------------------------------
# Trigger filter DSL
# ---------------------------------------------------------------------------

SUPPORTED_DSL_OPERATORS = frozenset(
    {"equals", "contains", "startsWith", "endsWith", "matchRegex"}
)

SUPPORTED_TRIGGER_TYPES = frozenset(
    {
        "customEvent", "linkClick", "click", "pageview", "domReady",
        "windowLoaded", "formSubmission", "historyChange", "jsError",
    }
)


def _dsl_to_gtm_filter(entry: dict) -> dict:
    """Convert a friendly DSL filter entry to GTM's verbose filter shape.

    Input: {"variable": "dl_browser", "operator": "equals", "value": "Chrome",
            "negate": False}
    Output: GTM filter dict with type + parameter list (arg0, arg1, optional
    negate boolean), matching the shape used in existing triggers (e.g.,
    trigger 77 in the cos-tags workspace).

    Auto-wraps `variable` in `{{...}}` if not already wrapped. Stringifies
    `value`. Raises ValueError on missing keys or unsupported operator.
    """
    if "variable" not in entry:
        raise ValueError("filter entry missing 'variable'")
    if "operator" not in entry:
        raise ValueError("filter entry missing 'operator'")
    if "value" not in entry:
        raise ValueError("filter entry missing 'value'")

    operator = entry["operator"]
    if operator not in SUPPORTED_DSL_OPERATORS:
        raise ValueError(
            f"filter entry: unsupported operator '{operator}'; "
            f"supported: {sorted(SUPPORTED_DSL_OPERATORS)}"
        )

    variable = entry["variable"]
    if not variable.startswith("{{"):
        variable = "{{" + variable + "}}"

    parameter = [
        {"type": "template", "key": "arg0", "value": variable},
        {"type": "template", "key": "arg1", "value": str(entry["value"])},
    ]
    if entry.get("negate"):
        parameter.append({"type": "boolean", "key": "negate", "value": "true"})

    return {"type": operator, "parameter": parameter}
```

- [ ] **Step 4: Run the tests to verify they all pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_create_trigger.py::TestDslToGtmFilter -v`
Expected: PASS — 13 tests pass (9 explicit + 5 parametrized minus 1 = 13; check the actual count is 13 because the parametrize covers 5 operators).

- [ ] **Step 5: Commit**

```bash
git add tests/test_create_trigger.py fastmcp_gtm_helpers.py
git commit -m "$(cat <<'EOF'
feat: add _dsl_to_gtm_filter helper for trigger filter DSL

Converts friendly {variable, operator, value, negate} dicts to the verbose
GTM filter shape used by the API. Backbone for the upcoming generalized
create_trigger.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `update_gtm_variable` happy path — `javascript=` shortcut

**Files:**
- Create: `tests/test_update_gtm_variable.py`
- Modify: `fastmcp_gtm_write_tools.py` (append after `delete_tag`, currently ends around line 690)

- [ ] **Step 1: Create the test file with the shared mock helper and the first failing test**

Write to `tests/test_update_gtm_variable.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_update_gtm_variable.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_gtm_variable'`.

- [ ] **Step 3: Append minimal `update_gtm_variable` implementation**

In `fastmcp_gtm_write_tools.py`, after the last existing tool (`delete_tag`), append:

```python


# ---------------------------------------------------------------------------
# Update variable
# ---------------------------------------------------------------------------


@mcp.tool()
async def update_gtm_variable(
    account_id: str,
    container_id: str,
    variable_id: str,
    *,
    name: str | None = None,
    parameters: list | None = None,
    javascript: str | None = None,
    notes: str | None = None,
    parent_folder_id: str | None = None,
    workspace_id: str = "1",
) -> dict:
    """Update an existing GTM variable in place (partial update).

    Fetches the variable, mutates only the fields you passed, then writes
    it back with fingerprint concurrency. Preserves the variable's ID so
    every tag/trigger reference to ``{{variable_name}}`` keeps working.

    For jsm (Custom JavaScript) variables, pass ``javascript=<source>`` as
    a shortcut; the tool builds the right parameter list for you. For any
    variable type, pass ``parameters=<list of GTM parameter dicts>`` to
    replace the parameter list directly. ``parameters`` and ``javascript``
    are mutually exclusive.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        variable_id: The variable ID to update
        name: New display name (optional)
        parameters: Raw GTM parameter list, replaces existing (optional)
        javascript: Custom JS source; jsm variables only (optional)
        notes: New notes (optional)
        parent_folder_id: New parent folder ID (optional)
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(
            account_id=account_id, container_id=container_id, variable_id=variable_id
        )
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(
            client, account_id, container_id, workspace_id
        )
        path = f"{ws_parent}/variables/{variable_id}"

        variable = await _run(
            client.service.accounts().containers().workspaces().variables().get(path=path)
        )

        updated_fields: list[str] = []

        if javascript is not None:
            variable["parameter"] = [
                {"type": "template", "key": "javascript", "value": javascript}
            ]
            updated_fields.append("parameters")

        updated = await _run(
            client.service.accounts().containers().workspaces().variables().update(
                path=path, body=variable, fingerprint=variable.get("fingerprint"),
            )
        )

        return {
            "status": "success",
            "message": f"Variable '{updated.get('name')}' updated",
            "variable_id": variable_id,
            "variable_name": updated.get("name"),
            "variable_type": updated.get("type"),
            "updated_fields": updated_fields,
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to update variable: {str(e)}"}
```

This is intentionally minimal — only `javascript=` is wired. Task 3 adds the other fields. Task 4 adds validation (mutual exclusion, jsm-only check, nothing-to-update).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_update_gtm_variable.py -v`
Expected: PASS — 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_update_gtm_variable.py fastmcp_gtm_write_tools.py
git commit -m "$(cat <<'EOF'
feat: add update_gtm_variable tool (javascript shortcut, happy path)

In-place update for jsm variables via a friendly javascript= argument.
Mirrors the GET-mutate-UPDATE-with-fingerprint pattern used by
update_tag_consent_settings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `update_gtm_variable` — raw `parameters`, `name`, `notes`, `parent_folder_id`

**Files:**
- Modify: `tests/test_update_gtm_variable.py` (append new test class)
- Modify: `fastmcp_gtm_write_tools.py` (extend `update_gtm_variable` body)

- [ ] **Step 1: Append failing tests for the remaining update paths**

Append to `tests/test_update_gtm_variable.py`:

```python


class TestUpdateGtmVariableOtherFields:
    @pytest.mark.asyncio
    async def test_raw_parameters_update_replaces_parameter_list(self):
        from fastmcp_gtm_write_tools import update_gtm_variable

        variable = {
            "name": "MY_VAR", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": [
                {"type": "template", "key": "value", "value": "old"}
            ],
        }
        client, variables = _make_mock_client(variable)
        new_params = [{"type": "template", "key": "value", "value": "new"}]

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
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
        from fastmcp_gtm_write_tools import update_gtm_variable

        original_params = [{"type": "template", "key": "value", "value": "x"}]
        variable = {
            "name": "OLD_NAME", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": original_params,
        }
        client, variables = _make_mock_client(variable)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
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
        from fastmcp_gtm_write_tools import update_gtm_variable

        variable = {
            "name": "V", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": [],
        }
        client, variables = _make_mock_client(variable)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
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
        from fastmcp_gtm_write_tools import update_gtm_variable

        variable = {
            "name": "V", "variableId": "10", "type": "c",
            "fingerprint": "fp", "parameter": [], "parentFolderId": "100",
        }
        client, variables = _make_mock_client(variable)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                parent_folder_id="200",
            )

        assert result["status"] == "success"
        assert result["updated_fields"] == ["parent_folder_id"]
        assert variables.update.call_args.kwargs["body"]["parentFolderId"] == "200"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_update_gtm_variable.py::TestUpdateGtmVariableOtherFields -v`
Expected: FAIL — assertions on `updated_fields` and on the body fields fail (current impl only handles `javascript`).

- [ ] **Step 3: Extend the `update_gtm_variable` body**

In `fastmcp_gtm_write_tools.py`, inside `update_gtm_variable`, replace the block that currently looks like:

```python
        updated_fields: list[str] = []

        if javascript is not None:
            variable["parameter"] = [
                {"type": "template", "key": "javascript", "value": javascript}
            ]
            updated_fields.append("parameters")
```

with:

```python
        updated_fields: list[str] = []

        if javascript is not None:
            variable["parameter"] = [
                {"type": "template", "key": "javascript", "value": javascript}
            ]
            updated_fields.append("parameters")
        elif parameters is not None:
            variable["parameter"] = parameters
            updated_fields.append("parameters")

        if name is not None:
            variable["name"] = name
            updated_fields.append("name")
        if notes is not None:
            variable["notes"] = notes
            updated_fields.append("notes")
        if parent_folder_id is not None:
            variable["parentFolderId"] = parent_folder_id
            updated_fields.append("parent_folder_id")
```

- [ ] **Step 4: Run the test file to verify all five tests pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_update_gtm_variable.py -v`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_update_gtm_variable.py fastmcp_gtm_write_tools.py
git commit -m "$(cat <<'EOF'
feat: support name/notes/parameters/parent_folder updates in update_gtm_variable

Extends the tool beyond the jsm javascript shortcut so callers can rename
variables, replace raw parameter lists, set notes, or move variables
between folders. Each call records what changed in updated_fields.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `update_gtm_variable` validation

**Files:**
- Modify: `tests/test_update_gtm_variable.py` (append new test class)
- Modify: `fastmcp_gtm_write_tools.py` (add validation block)

- [ ] **Step 1: Append failing validation tests**

Append to `tests/test_update_gtm_variable.py`:

```python


class TestUpdateGtmVariableValidation:
    @pytest.mark.asyncio
    async def test_empty_variable_id_returns_error(self):
        from fastmcp_gtm_write_tools import update_gtm_variable

        result = await update_gtm_variable(
            account_id="1", container_id="2", variable_id="",
            javascript="function() {}",
        )
        assert result["status"] == "error"
        assert "variable_id" in result["message"]

    @pytest.mark.asyncio
    async def test_nothing_to_update_returns_error(self):
        from fastmcp_gtm_write_tools import update_gtm_variable

        # All optional fields omitted. Must not call .get() or .update().
        variable = {"name": "V", "variableId": "10", "type": "c",
                    "fingerprint": "fp", "parameter": []}
        client, variables = _make_mock_client(variable)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
            )

        assert result["status"] == "error"
        assert "nothing to update" in result["message"].lower()
        variables.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_parameters_and_javascript_both_set_returns_error(self):
        from fastmcp_gtm_write_tools import update_gtm_variable

        result = await update_gtm_variable(
            account_id="1", container_id="2", variable_id="10",
            parameters=[{"type": "template", "key": "value", "value": "x"}],
            javascript="function() {}",
        )
        assert result["status"] == "error"
        assert "mutually exclusive" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_javascript_on_non_jsm_variable_returns_error(self):
        from fastmcp_gtm_write_tools import update_gtm_variable

        # Variable type is "v" (Data Layer Variable), not "jsm".
        variable = {"name": "DLV", "variableId": "10", "type": "v",
                    "fingerprint": "fp", "parameter": []}
        client, variables = _make_mock_client(variable)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await update_gtm_variable(
                account_id="1", container_id="2", variable_id="10",
                javascript="function() {}",
            )

        assert result["status"] == "error"
        assert "jsm" in result["message"]
        assert "'v'" in result["message"]
        variables.update.assert_not_called()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_update_gtm_variable.py::TestUpdateGtmVariableValidation -v`
Expected:
- `test_empty_variable_id_returns_error`: PASS already (`_validate_ids` enforces this).
- The other three: FAIL — validation not yet implemented.

- [ ] **Step 3: Add the validation blocks**

In `fastmcp_gtm_write_tools.py`, inside `update_gtm_variable`:

(a) Right after the `_validate_ids` block, add the mutual-exclusion + nothing-to-update checks:

```python
        if parameters is not None and javascript is not None:
            return {
                "status": "error",
                "message": "parameters and javascript are mutually exclusive",
            }
        if all(v is None for v in (name, parameters, javascript, notes, parent_folder_id)):
            return {
                "status": "error",
                "message": "nothing to update (pass at least one of name, parameters, javascript, notes, parent_folder_id)",
            }
```

(b) Right after the `variable = await _run(...get(path=path))` line and before any mutation, add the jsm guard:

```python
        if javascript is not None and variable.get("type") != "jsm":
            return {
                "status": "error",
                "message": (
                    f"javascript shortcut only valid for jsm variables; "
                    f"this variable is type '{variable.get('type')}'"
                ),
            }
```

- [ ] **Step 4: Run the full test file to verify all nine tests pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_update_gtm_variable.py -v`
Expected: PASS — 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_update_gtm_variable.py fastmcp_gtm_write_tools.py
git commit -m "$(cat <<'EOF'
feat: validate inputs for update_gtm_variable

Rejects calls with no fields to update, with both parameters and javascript
set, and with javascript passed to a non-jsm variable. Standard ID
validation is delegated to _validate_ids.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Generalize `create_trigger` — back-compat + non-customEvent path

**Files:**
- Modify: `tests/test_create_trigger.py` (append new test classes)
- Modify: `fastmcp_gtm_write_tools.py` (replace body of `create_trigger`, currently lines 312–372; import the new helper + constants)

- [ ] **Step 1: Append the failing back-compat and DSL test classes**

Append to `tests/test_create_trigger.py`:

```python


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_create_trigger.py::TestCreateTriggerBackCompat tests/test_create_trigger.py::TestCreateTriggerLinkClick -v`
Expected: FAIL — current `create_trigger` doesn't accept `trigger_type`/`filters` kwargs (TypeError), and the back-compat test fails because today's response dict has no `trigger_type` field.

- [ ] **Step 3: Update the import line in `fastmcp_gtm_write_tools.py`**

Find the existing import (around lines 13–17):

```python
from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run,
    _validate_consent_params, _build_consent_settings,
    _validate_ids, _resolve_workspace_parent,
)
```

Replace with:

```python
from fastmcp_gtm_helpers import (
    mcp, get_gtm_client, _run,
    _validate_consent_params, _build_consent_settings,
    _validate_ids, _resolve_workspace_parent,
    _dsl_to_gtm_filter, SUPPORTED_DSL_OPERATORS, SUPPORTED_TRIGGER_TYPES,
)
```

- [ ] **Step 4: Rewrite the `create_trigger` body**

In `fastmcp_gtm_write_tools.py`, replace the entire `create_trigger` function (currently lines 312–372) with:

```python
@mcp.tool()
async def create_trigger(
    account_id: str,
    container_id: str,
    trigger_name: str,
    *,
    trigger_type: str = "customEvent",
    event_name: str | None = None,
    filters: list | None = None,
    workspace_id: str = "1"
) -> dict:
    """Create a GTM trigger of the given type, with optional filter conditions.

    Two shapes are supported:

    1. customEvent (default): pass ``event_name`` to fire when
       dataLayer.push({'event': <event_name>}) occurs. ``filters`` may also
       be passed to add additional conditions on top of the event match.
    2. Any other supported type (linkClick, click, pageview, domReady,
       windowLoaded, formSubmission, historyChange, jsError): pass
       ``filters`` (required). Each filter is a friendly dict, e.g.
       ``{"variable": "dl_browser", "operator": "equals", "value": "Chrome",
       "negate": False}``. The tool converts to GTM's verbose filter shape.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        trigger_name: Display name for the trigger in GTM
        trigger_type: One of customEvent, linkClick, click, pageview,
            domReady, windowLoaded, formSubmission, historyChange, jsError.
            Defaults to customEvent.
        event_name: For customEvent only — the dataLayer event name to match.
        filters: List of friendly filter dicts (see DSL above). Required for
            non-customEvent types; optional extra filters for customEvent.
        workspace_id: GTM Workspace ID (auto-detected if omitted)
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id)
        if error:
            return {"status": "error", "message": error}

        if trigger_type not in SUPPORTED_TRIGGER_TYPES:
            return {
                "status": "error",
                "message": (
                    f"unsupported trigger_type '{trigger_type}'; "
                    f"supported: {sorted(SUPPORTED_TRIGGER_TYPES)}"
                ),
            }

        if trigger_type == "customEvent":
            if not event_name and not filters:
                return {
                    "status": "error",
                    "message": "customEvent requires event_name or filters",
                }
        else:
            if not filters:
                return {
                    "status": "error",
                    "message": f"trigger_type '{trigger_type}' requires filters",
                }

        client = get_gtm_client()
        workspace_id, parent = await _resolve_workspace_parent(
            client, account_id, container_id, workspace_id
        )

        trigger_body: dict = {"name": trigger_name, "type": trigger_type}

        if trigger_type == "customEvent":
            if event_name:
                trigger_body["customEventFilter"] = [
                    {
                        "type": "equals",
                        "parameter": [
                            {"key": "arg0", "value": "{{_event}}", "type": "template"},
                            {"key": "arg1", "value": event_name, "type": "template"},
                        ],
                    }
                ]
            if filters:
                trigger_body["filter"] = [_dsl_to_gtm_filter(f) for f in filters]
        else:
            trigger_body["filter"] = [_dsl_to_gtm_filter(f) for f in filters]

        result = await _run(
            client.service.accounts().containers().workspaces().triggers().create(
                parent=parent,
                body=trigger_body,
            )
        )

        return {
            "status": "success",
            "message": f"Trigger '{trigger_name}' created",
            "trigger_id": result.get("triggerId"),
            "trigger_name": trigger_name,
            "trigger_type": trigger_type,
            "path": result.get("path"),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create trigger: {str(e)}",
        }
```

- [ ] **Step 5: Run the test file to verify all 16 tests pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_create_trigger.py -v`
Expected: PASS — 13 helper tests + 1 back-compat + 2 linkClick/customEvent = 16 tests.

- [ ] **Step 6: Commit**

```bash
git add tests/test_create_trigger.py fastmcp_gtm_write_tools.py
git commit -m "$(cat <<'EOF'
feat: generalize create_trigger to support any trigger type + filter DSL

Adds trigger_type and filters keyword arguments to create_trigger. The
default trigger_type="customEvent" + event_name= path produces the same
body shape as before, so existing callers are unaffected. linkClick,
click, pageview, domReady, windowLoaded, formSubmission, historyChange,
and jsError now work with the friendly filter DSL backed by
_dsl_to_gtm_filter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `create_trigger` validation tests

**Files:**
- Modify: `tests/test_create_trigger.py` (append new test class)

- [ ] **Step 1: Append the failing validation tests**

Append to `tests/test_create_trigger.py`:

```python


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
```

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_create_trigger.py::TestCreateTriggerValidation -v`
Expected: PASS — 6 tests pass. (Validation is already wired in Task 5; these tests pin the contract.)

- [ ] **Step 3: Run the full test file to confirm no regressions**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_create_trigger.py -v`
Expected: PASS — 22 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_create_trigger.py
git commit -m "$(cat <<'EOF'
test: lock in create_trigger validation contract

Pins behavior for unsupported trigger types, missing event_name+filters on
customEvent, missing filters on non-customEvent types, bad DSL operators,
and invalid account IDs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Module bookkeeping + docs + final verification

**Files:**
- Modify: `fastmcp_gtm_write_tools.py` (module docstring at the top, lines 1–8)
- Modify: `README.md` (tool count + tool list)
- Modify: `AGENTS.md` (match README)

- [ ] **Step 1: Update the module docstring**

In `fastmcp_gtm_write_tools.py`, replace the current docstring (which says "11 tools" after the delete_tag work):

```python
"""
Write MCP tools for Google Tag Manager.

Registers 11 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
publish_gtm_container, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch, pause_tag, unpause_tag, delete_tag.
"""
```

with:

```python
"""
Write MCP tools for Google Tag Manager.

Registers 12 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
publish_gtm_container, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch, pause_tag, unpause_tag, delete_tag,
update_gtm_variable.
"""
```

- [ ] **Step 2: Update README.md**

Find the line in `README.md` that says "21 MCP tools" (around line 103). Replace with "22 MCP tools".

Then locate the section that lists the modifying tools — find the line documenting `create_trigger` and replace its description to mention the generalization:

Before (search for the existing line, format may vary):

```markdown
- `create_trigger` — Create a custom event trigger.
```

After:

```markdown
- `create_trigger` — Create a GTM trigger of any supported type (customEvent, linkClick, click, pageview, domReady, windowLoaded, formSubmission, historyChange, jsError) with a friendly filter DSL.
```

Add a new bullet for `update_gtm_variable` near the other update tools (look for `update_tag_consent_settings`). Insert below it:

```markdown
- `update_gtm_variable` — Update a GTM variable in place (name, parameters, notes, parent folder; `javascript=` shortcut for jsm variables).
```

Note: if the README uses a different markdown shape for the tool listing (table, indented list, sections), match the existing shape rather than the exact bullets above. Open the file and inspect first.

- [ ] **Step 3: Update AGENTS.md**

In `AGENTS.md`, find the same tool-count reference and the same tool listing (it's structured similarly to README). Make the same two changes: bump the count by one and add a line for `update_gtm_variable` next to the other update tools; update the `create_trigger` description.

- [ ] **Step 4: Run the full test suite**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest -v`
Expected: PASS — all previously-passing tests still pass; new tests for `update_gtm_variable` (9) and `create_trigger` (22) all pass. If any unrelated test fails, stop and investigate.

- [ ] **Step 5: Sanity-check that both tools are registered on the MCP**

Run:

```bash
cd /Users/kemberlymiliano/gtm-mcp && uv run python -c "
import fastmcp_gtm_server, fastmcp_gtm_write_tools
from fastmcp_gtm_helpers import mcp
import asyncio
tools = asyncio.run(mcp.get_tools())
names = set(tools.keys()) if isinstance(tools, dict) else {t.name for t in tools}
print('update_gtm_variable:', 'update_gtm_variable' in names)
print('create_trigger:', 'create_trigger' in names)
"
```

Expected:
```
update_gtm_variable: True
create_trigger: True
```

If `mcp.get_tools()` has a different signature on the installed FastMCP version, fall back to:

```bash
cd /Users/kemberlymiliano/gtm-mcp && uv run python -c "
import fastmcp_gtm_write_tools
print('update_gtm_variable' in dir(fastmcp_gtm_write_tools))
print('create_trigger' in dir(fastmcp_gtm_write_tools))
"
```

and confirm both print `True`.

- [ ] **Step 6: Commit**

```bash
git add fastmcp_gtm_write_tools.py README.md AGENTS.md
git commit -m "$(cat <<'EOF'
chore: bump module tool count to 12 and document new tools

Updates the module docstring, README, and AGENTS.md to reflect the new
update_gtm_variable tool and the generalized create_trigger.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

- **Spec coverage:**
  - `_dsl_to_gtm_filter` helper + constants in helpers module → Task 1.
  - `update_gtm_variable` signature with all five keyword-only fields → Task 2 (skeleton) + Task 3 (other fields) + Task 4 (validation).
  - GET-mutate-UPDATE-with-fingerprint pattern → Task 2.
  - `javascript=` jsm shortcut + jsm-only guard → Task 2 + Task 4.
  - `parameters`/`javascript` mutual exclusion → Task 4.
  - "nothing to update" error → Task 4.
  - `updated_fields` in success response → Task 2 + Task 3.
  - Generalized `create_trigger` signature with `trigger_type`/`filters`/`event_name` keyword-only → Task 5.
  - Supported trigger types set + validation → Task 5 + Task 6.
  - DSL operators (equals, contains, startsWith, endsWith, matchRegex) → Task 1.
  - Negate handling → Task 1 + Task 5 (linkClick test asserts the boolean parameter entry).
  - Auto-wrap of unwrapped variable names → Task 1.
  - customEvent back-compat (today's body shape preserved) → Task 5.
  - customEvent with extra `filters` adds both sections → Task 5.
  - Non-customEvent body has `filter` and no `customEventFilter` → Task 5.
  - Validation errors per spec table → Task 4 (variable) + Task 6 (trigger).
  - Module docstring count 11 → 12 → Task 7.
  - README + AGENTS.md updates → Task 7.
  - Cos-tags worked example (variable 425 + new linkClick trigger + attach to tag 80) is enabled end-to-end by the tools delivered in Tasks 2–6, with the attach step still using the pre-existing `add_firing_trigger_to_tags_batch`.

- **Placeholder scan:** No TBDs, no "implement appropriate ...", no "similar to Task N". Every code block is complete. Task 7 step 2 contains a "if shape differs, inspect first" hedge for the README, which is a real instruction rather than a placeholder — the engineer is asked to match an existing markdown shape that can vary; the substantive content (count bump, new bullet, updated description) is fully specified.

- **Type / name consistency:**
  - `update_gtm_variable` signature is identical across Tasks 2, 3, 4.
  - `create_trigger` signature is identical across Tasks 5, 6.
  - `_dsl_to_gtm_filter` is defined once in Task 1 and imported into write_tools in Task 5.
  - `_make_mock_client` (for variables) is defined once in Task 2 and reused by name in Tasks 3, 4.
  - `_make_mock_trigger_client` is defined once in Task 5 and reused by name in Task 6.
  - Field names in returns (`status`, `message`, `variable_id`, `variable_name`, `variable_type`, `updated_fields`, `trigger_id`, `trigger_name`, `trigger_type`, `path`) match between implementation and assertions throughout.
  - Resource paths consistent: `accounts/<account>/containers/<container>/workspaces/<ws>/variables/<id>` and `…/triggers/<id>`.
  - Constant names (`SUPPORTED_DSL_OPERATORS`, `SUPPORTED_TRIGGER_TYPES`) used identically in the helper module and the import in write_tools.

No issues found.
