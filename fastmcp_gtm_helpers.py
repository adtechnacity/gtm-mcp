"""
Shared server instance and helpers for GTM MCP tools.

Creates the FastMCP server, GTM client, and internal helpers used by both
read and write tool modules. Import from here — never instantiate separately.
"""
import asyncio
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


async def _create_datalayer_var(client, parent, name, key):
    """Create a single Data Layer Variable and return its result dict."""
    variable_body = {
        'name': name, 'type': 'v',
        'parameter': [
            {'key': 'dataLayerVersion', 'value': '2', 'type': 'template'},
            {'key': 'setDefaultValue', 'value': 'false', 'type': 'template'},
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
