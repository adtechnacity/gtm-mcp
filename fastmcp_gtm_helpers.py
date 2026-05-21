"""
Shared server instance and helpers for GTM MCP tools.

Creates the FastMCP server, GTM client, and internal helpers used by both
read and write tool modules. Import from here — never instantiate separately.
"""
import asyncio
import copy
import logging
import sys

# Redirect logging to stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gtm-fastmcp-server")

from mcp.server import FastMCP

# Initialize the MCP server
mcp = FastMCP("gtm-fastmcp-server")

# GTM client initialization
gtm_client = None


def get_gtm_client():
    """Lazy initialization of GTM client"""
    global gtm_client
    if gtm_client is None:
        try:
            from gtm_client_fixed import GTMClient
            gtm_client = GTMClient()
            logger.info("GTM client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GTM client: {e}")
            raise Exception(f"GTM authentication failed: {e}. Please ensure GOOGLE_APPLICATION_CREDENTIALS is set.")
    return gtm_client


async def _run(request):
    """Run a blocking Google API request in a thread pool."""
    result = await asyncio.to_thread(request.execute)
    if result is None:
        return {}
    return result


# Load GTM components
try:
    from gtm_components import GTMComponentTemplates, GTMWorkflowBuilder
    HAS_GTM_COMPONENTS = True
    logger.info("GTM components loaded successfully")
except ImportError as e:
    logger.error(f"Failed to load GTM components: {e}")
    HAS_GTM_COMPONENTS = False


# ---------------------------------------------------------------------------
# Internal helpers — shared logic extracted from tool functions
# ---------------------------------------------------------------------------

MAX_BATCH_SIZE = 50

# Cache for resolved workspace IDs: (account_id, container_id) → workspace_id
_workspace_cache: dict[tuple[str, str], str] = {}


async def _resolve_workspace_id(client, account_id: str, container_id: str, workspace_id: str) -> str:
    """Resolve workspace_id, auto-detecting if the caller passed the default '1'.

    GTM workspace IDs are not always '1'. When the default is used, this
    function lists the container's workspaces and returns the first one found.
    Results are cached per (account, container) pair for the server's lifetime.
    """
    if workspace_id != "1":
        if not str(workspace_id).strip().isdigit():
            raise ValueError(f"Invalid workspace_id: '{workspace_id}'. Must be a numeric string.")
        return workspace_id

    cache_key = (account_id, container_id)
    if cache_key in _workspace_cache:
        return _workspace_cache[cache_key]

    parent = f"accounts/{account_id}/containers/{container_id}"
    result = await _run(
        client.service.accounts().containers().workspaces().list(parent=parent)
    )
    workspaces = result.get("workspace", [])
    if not workspaces:
        logger.warning("No workspaces found for container %s; falling back to workspace_id='%s'", container_id, workspace_id)
        _workspace_cache[cache_key] = workspace_id
        return workspace_id

    # Check if workspace "1" actually exists
    ws_ids = [w.get("workspaceId") for w in workspaces if w.get("workspaceId")]
    if not ws_ids:
        logger.warning("No valid workspace IDs found for container %s", container_id)
        _workspace_cache[cache_key] = workspace_id
        return workspace_id
    if "1" in ws_ids:
        _workspace_cache[cache_key] = "1"
        return "1"

    # Use the first workspace found
    resolved = ws_ids[0]
    _workspace_cache[cache_key] = resolved
    logger.info(
        "Auto-resolved workspace_id to '%s' (container %s has no workspace '1')",
        resolved, container_id,
    )
    return resolved


async def _resolve_workspace_parent(client, account_id: str, container_id: str, workspace_id: str = "1") -> tuple[str, str]:
    """Resolve workspace ID and build the workspace parent path in one call."""
    ws_id = await _resolve_workspace_id(client, account_id, container_id, workspace_id)
    return ws_id, f"accounts/{account_id}/containers/{container_id}/workspaces/{ws_id}"


def _validate_gtm_id(value, name="ID"):
    """Validate that a GTM ID is a non-empty numeric string. Returns error message or None."""
    if not value or not str(value).strip().isdigit():
        return f"Invalid {name}: '{value}'. Must be a non-empty numeric string."
    return None


def _validate_ids(**ids):
    """Validate multiple GTM ID parameters. Returns first error or None."""
    for name, value in ids.items():
        error = _validate_gtm_id(value, name)
        if error:
            return error
    return None


async def _paginated_list(request_fn, result_key):
    """Fetch all pages from a GTM API list endpoint.

    request_fn → callable returning a Google API request object.
    result_key → key in response containing the list items (e.g. 'tag', 'variable').
    """
    items = []
    request = request_fn()
    while request is not None:
        result = await _run(request)
        items.extend(result.get(result_key, []))
        next_token = result.get('nextPageToken')
        if not next_token:
            break
        request = request_fn(pageToken=next_token)
    return items

_VALID_CONSENT_STATUSES = ("notSet", "notNeeded", "needed")


def _validate_consent_params(consent_status, consent_types):
    """Return error message string, or None if valid."""
    if consent_status not in _VALID_CONSENT_STATUSES:
        return f"Invalid consent_status '{consent_status}'. Must be 'notSet', 'notNeeded', or 'needed'."
    if consent_status == "needed" and not consent_types:
        return "consent_types is required when consent_status is 'needed'."
    return None


def _build_consent_settings(consent_status, consent_types):
    """Build GTM consentSettings dict from validated parameters."""
    settings = {"consentStatus": consent_status}
    if consent_status == "needed" and consent_types:
        settings["consentType"] = {
            "type": "list",
            "list": [{"type": "template", "value": ct} for ct in consent_types],
        }
    return settings


def _validate_trigger_filters(filters):
    """Validate user-provided trigger filter conditions.

    Each item must be a dict with string ``type`` and list ``parameter``,
    where each parameter is a dict with ``key``, ``value``, and ``type``.
    Returns an error message string, or None if valid. An empty list is valid
    (used to clear a filter list wholesale).
    """
    if not isinstance(filters, list):
        return "filters must be a list of condition dicts"
    for i, cond in enumerate(filters):
        if not isinstance(cond, dict):
            return f"filters[{i}] must be a dict"
        if not isinstance(cond.get("type"), str) or not cond["type"]:
            return f"filters[{i}].type must be a non-empty string"
        params = cond.get("parameter")
        if not isinstance(params, list) or not params:
            return f"filters[{i}].parameter must be a non-empty list"
        for j, p in enumerate(params):
            if not isinstance(p, dict) or not all(isinstance(p.get(k), str) for k in ("key", "value", "type")):
                return f"filters[{i}].parameter[{j}] must be a dict with string key/value/type"
    return None


def _filter_tuples_to_conditions(tuples):
    """Convert ``[{operator, lhs, rhs}, ...]`` to GTM Condition dicts.

    Each tuple becomes a Condition with ``type=operator`` and two template
    parameters (``arg0=lhs``, ``arg1=rhs``). This is the ergonomic form most
    callers want — they say "Page Path matchRegex /create" instead of hand-
    rolling the parameter list. Raises ValueError on bad input.
    """
    if not isinstance(tuples, list) or not tuples:
        raise ValueError("conditions must be a non-empty list")
    result = []
    for i, t in enumerate(tuples):
        if not isinstance(t, dict):
            raise ValueError(f"conditions[{i}] must be a dict with operator/lhs/rhs")
        operator = t.get("operator")
        lhs = t.get("lhs")
        rhs = t.get("rhs")
        for name, value in (("operator", operator), ("lhs", lhs), ("rhs", rhs)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"conditions[{i}].{name} must be a non-empty string")
        result.append({
            "type": operator,
            "parameter": [
                {"type": "template", "key": "arg0", "value": lhs},
                {"type": "template", "key": "arg1", "value": rhs},
            ],
        })
    return result


def _upsert_parameters(existing, updates):
    """Upsert GTM parameter dicts into ``existing`` by their ``key`` field.

    For each item in ``updates``, replaces the parameter sharing the same ``key``
    in ``existing`` or appends it. Returns a new list; inputs are not mutated.
    Raises ValueError on missing ``key``/``type`` or duplicate keys in updates.

    The caller is responsible for the inner shape of each update dict — value
    fields must match the GTM parameter ``type`` (``value`` for template/boolean/
    integer, ``list`` for list, ``map`` for map).
    """
    if not isinstance(updates, list):
        raise ValueError("updates must be a list of parameter dicts.")
    seen_keys = set()
    for u in updates:
        if not isinstance(u, dict):
            raise ValueError(f"Each update must be a dict, got {type(u).__name__}.")
        key = u.get("key")
        if not key or not isinstance(key, str):
            raise ValueError("Each update must have a non-empty string 'key'.")
        if not u.get("type"):
            raise ValueError(f"Update for key '{key}' is missing 'type'.")
        if key in seen_keys:
            raise ValueError(f"Duplicate key '{key}' in updates.")
        seen_keys.add(key)

    by_key = {p.get("key"): i for i, p in enumerate(existing or [])}
    result = list(existing or [])
    for u in updates:
        item = copy.deepcopy(u)
        idx = by_key.get(item["key"])
        if idx is None:
            by_key[item["key"]] = len(result)
            result.append(item)
        else:
            result[idx] = item
    return result


async def _create_datalayer_var(client, parent, name, key):
    """Create a single Data Layer Variable and return its result dict."""
    variable_body = {
        'name': name, 'type': 'v',
        'parameter': [
            {'key': 'dataLayerVersion', 'value': '2', 'type': 'integer'},
            {'key': 'setDefaultValue', 'value': 'false', 'type': 'boolean'},
            {'key': 'name', 'value': key, 'type': 'template'},
        ],
    }
    result = await _run(client.service.accounts().containers().workspaces().variables().create(
        parent=parent, body=variable_body))
    return {"name": name, "key": key, "variable_id": result.get('variableId')}


async def _update_one_tag(client, path, mutate_fn, extra_fields_fn=None):
    """Fetch, mutate, and update a single tag.

    Returns ("updated", entry) or ("skipped", entry).
    Raises on API errors — caller handles exceptions.
    """
    tag = await _run(client.service.accounts().containers().workspaces().tags().get(path=path))
    mutated = mutate_fn(tag)
    tag_id = path.rsplit("/", 1)[-1]
    if mutated is None:
        return "skipped", {"tag_id": tag_id, "tag_name": tag.get("name")}
    updated = await _run(client.service.accounts().containers().workspaces().tags().update(
        path=path, body=mutated, fingerprint=mutated.get("fingerprint")))
    entry = {"tag_id": tag_id, "tag_name": updated.get("name")}
    if extra_fields_fn:
        entry.update(extra_fields_fn(updated))
    return "updated", entry


async def _batch_update_tags(client, path_prefix, tag_ids, mutate_fn,
                             extra_fields_fn=None, skip_reason=None):
    """Fetch, mutate, and update multiple tags.

    path_prefix → "accounts/{id}/containers/{id}/workspaces/{id}" base path.
    mutate_fn(tag) → modified tag dict to proceed, or None to skip.
    extra_fields_fn(updated_tag) → dict of extra fields for updated entries (optional).
    skip_reason → static reason string added to skipped entries (optional).
    """
    if len(tag_ids) > MAX_BATCH_SIZE:
        return {"status": "error", "message": f"Batch size {len(tag_ids)} exceeds limit of {MAX_BATCH_SIZE}."}
    for tid in tag_ids:
        error = _validate_gtm_id(tid, "tag_id")
        if error:
            return {"status": "error", "message": error}
    results = {"updated": [], "skipped": [], "failed": []}
    for tag_id in tag_ids:
        try:
            category, entry = await _update_one_tag(
                client, f"{path_prefix}/tags/{tag_id}",
                mutate_fn, extra_fields_fn)
            if category == "skipped" and skip_reason:
                entry["reason"] = skip_reason
            results[category].append(entry)
        except Exception as e:
            results["failed"].append({"tag_id": tag_id, "error": str(e)})
    n_updated, n_failed, n_skipped = len(results["updated"]), len(results["failed"]), len(results["skipped"])
    results["status"] = "error" if n_failed and not n_updated else "partial" if n_failed else "success"
    results["summary"] = f"Updated {n_updated}/{len(tag_ids)} tags, skipped {n_skipped}, failed {n_failed}"
    return results


async def _append_trigger_to_tags_batch(
    client, path_prefix, tag_ids, trigger_id, *, field, label, skip_reason
):
    """Append a trigger ID to either ``firingTriggerId`` or ``blockingTriggerId`` across tags."""
    def append(tag):
        existing = tag.get(field, [])
        if trigger_id in existing:
            return None
        tag[field] = existing + [trigger_id]
        return tag
    return await _batch_update_tags(
        client, path_prefix, tag_ids, append,
        extra_fields_fn=lambda t: {label: t.get(field, [])},
        skip_reason=skip_reason,
    )


async def _remove_trigger_from_tags_batch(
    client, path_prefix, tag_ids, trigger_id, *, field, label, skip_reason
):
    """Remove a trigger ID from ``firingTriggerId`` or ``blockingTriggerId`` across tags."""
    def remove(tag):
        existing = tag.get(field, [])
        if trigger_id not in existing:
            return None
        tag[field] = [t for t in existing if t != trigger_id]
        return tag
    return await _batch_update_tags(
        client, path_prefix, tag_ids, remove,
        extra_fields_fn=lambda t: {label: t.get(field, [])},
        skip_reason=skip_reason,
    )


async def _set_triggers_on_tags_batch(
    client, path_prefix, tag_ids, trigger_ids, *, field, label, skip_reason
):
    """Replace the ``firingTriggerId`` or ``blockingTriggerId`` list with ``trigger_ids``."""
    new_list = list(trigger_ids)
    def set_list(tag):
        if tag.get(field, []) == new_list:
            return None
        tag[field] = new_list
        return tag
    return await _batch_update_tags(
        client, path_prefix, tag_ids, set_list,
        extra_fields_fn=lambda t: {label: t.get(field, [])},
        skip_reason=skip_reason,
    )
