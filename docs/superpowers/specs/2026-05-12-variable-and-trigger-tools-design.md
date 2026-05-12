# `update_gtm_variable` + generalized `create_trigger` — design

**Date:** 2026-05-12
**Branch:** `feature/variable-and-trigger-tools` (off `feature/pause-tag-tools`)
**Status:** Approved, ready for implementation plan

## Motivation

Two real cos-tags edits are blocked by missing MCP coverage:

1. **Simplify the `isOOPage` jsm variable** (id 425) so it returns true only when the page path contains `-oocta`. Six tags reference `{{isOOPage}}`, so delete-and-recreate is not viable — the variable must be updated in place.
2. **Add a new linkClick trigger** for mobile Chrome on `/ma/` paths and attach it to the "Google Ads Conversion (CTA Clickout)" tag (id 80). No existing trigger matches that condition; one must be created.

Today's MCP can do neither: there is no variable-update tool, and `create_trigger` only builds `customEvent` triggers. `add_firing_trigger_to_tags_batch` covers step 3 of the trigger flow but is blocked on step 2.

## Scope

- **New tool:** `update_gtm_variable` — partial update of any GTM variable (name, parameters, notes, parentFolderId) using GET-mutate-UPDATE with fingerprint. Includes a `javascript=` ergonomic shortcut for jsm variables.
- **Generalized tool:** `create_trigger` — same name, expanded to accept `trigger_type` + a friendly-DSL `filters=` list. Backward compatible: an old-style call with only `event_name=` still produces the same `customEvent` trigger body as today.
- **Out of scope (YAGNI):** update_gtm_trigger, delete_gtm_variable additions, batch variants, trigger types that need extra config (scrollDepth, timer, elementVisibility, youTubeVideo), filter operators beyond the five named below.

## Tool spec — `update_gtm_variable`

**Location:** `fastmcp_gtm_write_tools.py`, alongside the other update tools.

**Signature:**

```python
@mcp.tool()
async def update_gtm_variable(
    account_id: str,
    container_id: str,
    variable_id: str,
    *,
    name: str | None = None,
    parameters: list[dict] | None = None,   # raw GTM parameter list; replaces existing
    javascript: str | None = None,          # jsm-only shortcut
    notes: str | None = None,
    parent_folder_id: str | None = None,
    workspace_id: str = "1",
) -> dict:
```

**Semantics:**

1. Validate IDs with `_validate_ids`. Return `{"status": "error", ...}` on failure.
2. Reject the call if all five optional inputs (`name`, `parameters`, `javascript`, `notes`, `parent_folder_id`) are `None` — no-op call returns `{"status": "error", "message": "nothing to update"}`.
3. Reject if both `parameters` and `javascript` are passed — they're mutually exclusive (the shortcut just builds `parameters` for you).
4. Fetch the variable: `client.service.accounts().containers().workspaces().variables().get(path=...)`.
5. If `javascript` is set, verify `variable["type"] == "jsm"` — otherwise return `{"status": "error", "message": "javascript shortcut only valid for jsm variables; this variable is type '<type>'"}`. Build `parameters = [{"type": "template", "key": "javascript", "value": <src>}]` internally.
6. Mutate only the fields that were passed: `variable["name"] = name` if `name is not None`, etc.
7. Update with fingerprint: `variables().update(path=..., body=variable, fingerprint=variable.get("fingerprint"))`.
8. Return:

```python
{
    "status": "success",
    "message": f"Variable '{updated['name']}' updated",
    "variable_id": variable_id,
    "variable_name": updated["name"],
    "variable_type": updated["type"],
    "updated_fields": [...],  # subset of ["name","parameters","notes","parent_folder_id"]
}
```

`updated_fields` records what was actually changed (treats `javascript` as `"parameters"`). On any caught exception, return `{"status": "error", "message": f"Failed to update variable: {str(e)}"}`.

## Tool spec — `create_trigger` (generalized)

**Location:** `fastmcp_gtm_write_tools.py`, replacing the existing function in place.

**Signature:**

```python
@mcp.tool()
async def create_trigger(
    account_id: str,
    container_id: str,
    trigger_name: str,
    *,
    trigger_type: str = "customEvent",
    event_name: str | None = None,
    filters: list[dict] | None = None,
    workspace_id: str = "1",
) -> dict:
```

**Supported `trigger_type` values (v1):** `customEvent`, `linkClick`, `click`, `pageview`, `domReady`, `windowLoaded`, `formSubmission`, `historyChange`, `jsError`. Anything else → validation error listing the supported set.

**Filter DSL entry shape:**

```python
{"variable": "dl_browser", "operator": "equals", "value": "Chrome", "negate": False}
```

- `variable` (required): GTM variable name. If it does not already start with `{{`, the helper wraps it as `{{<name>}}`. Built-ins like `Page URL` work either wrapped or unwrapped.
- `operator` (required): one of `equals`, `contains`, `startsWith`, `endsWith`, `matchRegex`. Anything else → validation error listing the supported set.
- `value` (required): literal string used as the right-hand side.
- `negate` (optional, default `False`): when `True`, adds the `{"type":"boolean","key":"negate","value":"true"}` parameter that GTM uses for "does not …".

**Per-type behavior:**

- `customEvent`:
  - If `event_name` is given and `filters` is `None` or empty → build today's exact body (`type: customEvent`, `customEventFilter` with `{{_event}}` equals shortcut). This is the back-compat path.
  - If `filters` is given, prepend the event-name match into `customEventFilter` and put DSL-converted filters into `filter`.
  - If neither `event_name` nor `filters` is given → validation error.
- All other types:
  - `filters` must be non-empty. Body shape: `{"name": ..., "type": <trigger_type>, "filter": [<dsl-converted>]}`. No `customEventFilter`.
  - `event_name` is ignored if passed (with no error).

Returns:

```python
{
    "status": "success",
    "message": f"Trigger '{trigger_name}' created",
    "trigger_id": result["triggerId"],
    "trigger_name": trigger_name,
    "trigger_type": trigger_type,
    "path": result["path"],
}
```

## Internal helper — `_dsl_to_gtm_filter`

```python
def _dsl_to_gtm_filter(entry: dict) -> dict:
    """Convert a friendly DSL filter entry to GTM's verbose filter shape."""
```

- Validates `variable`/`operator`/`value` presence and `operator` membership.
- Auto-wraps `entry["variable"]` in `{{...}}` if not already wrapped.
- Emits:

```python
{
    "type": entry["operator"],          # equals / contains / startsWith / endsWith / matchRegex
    "parameter": [
        {"type": "template", "key": "arg0", "value": <wrapped variable>},
        {"type": "template", "key": "arg1", "value": str(entry["value"])},
        # appended only if entry.get("negate"):
        {"type": "boolean",  "key": "negate", "value": "true"},
    ],
}
```

Helper lives in `fastmcp_gtm_helpers.py` alongside `_build_consent_settings` and `_validate_ids`, and is imported into `fastmcp_gtm_write_tools.py` like the others.

## Validation rules at a glance

| Tool | Condition | Error |
|---|---|---|
| `update_gtm_variable` | empty account/container/variable id | `_validate_ids` standard message |
| `update_gtm_variable` | all updatable fields `None` | `"nothing to update"` |
| `update_gtm_variable` | both `parameters` and `javascript` set | `"parameters and javascript are mutually exclusive"` |
| `update_gtm_variable` | `javascript` passed but variable type ≠ `jsm` | `"javascript shortcut only valid for jsm variables; this variable is type '<type>'"` |
| `create_trigger` | `trigger_type` not in supported set | `"unsupported trigger_type '<x>'; supported: ..."` |
| `create_trigger` | `customEvent` with neither `event_name` nor `filters` | `"customEvent requires event_name or filters"` |
| `create_trigger` | non-customEvent with no `filters` | `"trigger_type '<x>' requires filters"` |
| `_dsl_to_gtm_filter` | missing key, bad operator | `"filter entry: <details>"` |

## Backward compatibility

The single behavioral change to `create_trigger`: existing callers passing `event_name` positionally (4th positional arg) still work because the parameter name and order are preserved. Callers who relied on the trailing `workspace_id` positional are unchanged. New params (`trigger_type`, `filters`) are keyword-only with defaults. Net: no existing tests break, no existing MCP invocations break.

## Testing

New file: `tests/test_update_gtm_variable.py`. Mirrors `tests/test_pause_tag.py` patterns (`_make_mock_client` style, `@pytest.mark.asyncio`, patch `get_gtm_client` and `_resolve_workspace_parent`).

Cases:

1. happy path — `javascript=` shortcut on a jsm variable; assert fingerprint passed and body's parameter list replaced.
2. happy path — `parameters=` raw list update.
3. happy path — `name`-only update; parameter list untouched.
4. happy path — combined `name` + `notes` update; updated_fields lists both.
5. validation — empty IDs.
6. validation — all-`None` call.
7. validation — both `parameters` and `javascript`.
8. validation — `javascript` on a non-jsm variable (mock returns `type: "v"`).

New file: `tests/test_create_trigger.py`. Cases:

1. back-compat — `event_name="foo"`, no `trigger_type` → produces a body structurally equal to today's output (same `type`, same `customEventFilter` shape with `{{_event}}` equals shortcut, no `filter` section).
2. customEvent with additional `filters` — body has both `customEventFilter` and `filter` sections.
3. linkClick happy path — three-filter DSL list converts to GTM shape; trigger 77 is a useful real-world reference.
4. negate-true converts to the boolean parameter entry.
5. auto-wrap — `variable="dl_browser"` → `{{dl_browser}}`; already-wrapped passes through unchanged.
6. validation — unsupported `trigger_type`.
7. validation — `customEvent` with neither input.
8. validation — `linkClick` with empty `filters`.
9. validation — bad operator.

The DSL helper gets its own unit tests inside `test_create_trigger.py` (no separate file needed).

## Module bookkeeping

- `fastmcp_gtm_write_tools.py` module docstring: tool count **11 → 12** (added `update_gtm_variable`; `create_trigger` stays one tool).
- `README.md` "21 MCP tools" → **22**, with a new line for `update_gtm_variable` and an updated description for `create_trigger`.
- `AGENTS.md` table updated to match.

## File touch list

- `fastmcp_gtm_write_tools.py` — add `update_gtm_variable`, rewrite `create_trigger`, add `_dsl_to_gtm_filter`. Update docstring count.
- `fastmcp_gtm_helpers.py` — add `_dsl_to_gtm_filter`.
- `tests/test_update_gtm_variable.py` — new.
- `tests/test_create_trigger.py` — new.
- `README.md` — counts and tool list.
- `AGENTS.md` — counts and tool list.
- `docs/superpowers/plans/2026-05-12-variable-and-trigger-tools.md` — implementation plan, written next.

## Worked example — the cos-tags edits this unblocks

```python
# 1. Simplify isOOPage (var 425). The six tags referencing {{isOOPage}} are unaffected.
await update_gtm_variable(
    account_id="1265057312", container_id="230044048", workspace_id="54",
    variable_id="425",
    javascript="function() {\n  return {{Page Path}}.indexOf('-oocta') !== -1;\n}",
)

# 2. Create the new linkClick trigger (mirrors trigger 77's pattern, Chrome + /ma/).
new_trig = await create_trigger(
    account_id="1265057312", container_id="230044048", workspace_id="54",
    trigger_name="Chrome Mobile Click Outs - /ma/ Enabled",
    trigger_type="linkClick",
    filters=[
        {"variable": "dl_browser", "operator": "equals", "value": "Chrome"},
        {"variable": "Page URL", "operator": "contains", "value": "/ma/"},
        {"variable": "VENDOR_G_ADS_CONVERSION_ID", "operator": "equals",
         "value": "null", "negate": True},
    ],
)

# 3. Attach to tag 80 alongside existing triggers 74-79.
await add_firing_trigger_to_tags_batch(
    account_id="1265057312", container_id="230044048", workspace_id="54",
    tag_ids=["80"], trigger_id=new_trig["trigger_id"],
)
```
