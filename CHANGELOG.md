# Changelog

## [0.2.1] - 2026-04-20

### Added
- `delete_tag` tool — delete a tag from a workspace (tagmanager.accounts.containers.workspaces.tags.delete)

### Changed
- AGENTS.md capability matrix marks `tags.delete` as implemented; stale `tags.delete` / `triggers.delete` entries removed from the Future Implementation priority list

## [0.2.0] - 2026-04-17

### Added
- `create_js_variable` tool — create a Custom JavaScript variable (type `jsm`)
- `update_tag_html` tool — replace the HTML body of a Custom HTML tag (guards on `type == "html"`, uses fingerprint concurrency)
- `delete_trigger` tool — delete a trigger from a workspace
- `add_blocking_trigger_to_tags_batch` tool — attach a blocking (exception) trigger to multiple tags
- `set_firing_triggers_on_tags_batch` tool — replace the firing-trigger list on multiple tags (for migrating between triggers in a single call)
- `remove_firing_trigger_from_tags_batch` tool — detach a specific firing trigger from multiple tags
- `remove_blocking_trigger_from_tags_batch` tool — detach a specific blocking trigger from multiple tags
- `create_trigger` now supports all common GTM trigger types via `trigger_type` parameter (`pageview`, `init`, `consentInit`, `domReady`, `windowLoaded`, `click`, `linkClick`, `formSubmission`, `scrollDepth`, `elementVisibility`, `timer`, `historyChange`, `youTubeVideo`, `triggerGroup`, `pageviewGtm`, `serverPageview`, plus `customEvent`)
- `create_trigger` accepts optional `filters` — additional GTM Condition dicts AND-ed with the trigger's base match (maps to the trigger body's `filter` field)

### Changed
- `create_trigger` validates `trigger_type` against the supported set and `filters` shape client-side (each entry must be `{type: str, parameter: [{key, value, type}, ...]}`)
- `create_trigger` no longer requires `event_name` except when `trigger_type == "customEvent"`
- `add_firing_trigger_to_tags_batch`, `add_blocking_trigger_to_tags_batch`, `set_firing_triggers_on_tags_batch`, `remove_firing_trigger_from_tags_batch`, and `remove_blocking_trigger_from_tags_batch` share helpers in `fastmcp_gtm_helpers` (`_append_trigger_to_tags_batch`, `_remove_trigger_from_tags_batch`, `_set_triggers_on_tags_batch`) on top of the existing `_batch_update_tags` primitive

### Fixed
- Data Layer Variable creation now sends `dataLayerVersion` as `integer` and `setDefaultValue` as `boolean`, matching the GTM Parameter schema (previously sent as `template`, which GTM tolerated but misrepresented)

## [0.1.1] - 2026-03-04

### Fixed
- Auto-resolve GTM workspace ID instead of defaulting to "1" — the GTM API silently returns empty arrays for non-existent workspace IDs, causing `list_gtm_tags`, `list_gtm_variables`, and `list_gtm_triggers` to appear to work but return no results
- Validate explicitly-provided `workspace_id` values (must be numeric)
- Cache resolved workspace IDs per (account, container) pair to avoid repeated API calls
- Cache fallback paths now correctly store results to prevent redundant API calls

### Security
- Validate batch `tag_ids` in `_batch_update_tags` to prevent non-numeric IDs in API paths
- Validate batch `variables` list items have required `name` and `key` fields
- Add input validation to CLI arguments (`account_id`, `container_id`, `workspace_id`, `tag_id`)
- Exclude `.mcp.json` from version control (contains machine-specific credential paths)

## [0.1.0] - 2026-03-04

### Added
- Generic `create_tag` tool supporting any GTM tag type (GA4, Custom HTML, Facebook Pixel, Google Ads, etc.) with full GTM API v2 Tag resource fields
- Input validation on all 18 tools — numeric-only GTM IDs prevent cross-account path traversal
- Pagination support for all list tools — no more silently truncated results
- Batch size limits (max 50) on bulk operations
- `create_trigger` tool for custom event triggers
- `create_datalayer_variable` and `create_datalayer_variables_batch` tools
- Consent management tools: `update_tag_consent_settings`, `update_tags_consent_settings_batch`
- `add_firing_trigger_to_tags_batch` for bulk trigger attachment
- `generate_ga4_template` for local GA4 tag JSON generation (no API calls)
- `publish_gtm_container` for workspace publishing
- CLI tool with 7 read-only subcommands
- Test suite (33 tests) covering validation, consent, and component templates
- Service account authentication (headless, no browser flow)

### Changed
- Split monolithic server into 3 modules: `fastmcp_gtm_helpers.py`, `fastmcp_gtm_server.py`, `fastmcp_gtm_write_tools.py`
- Made MCP vendor-agnostic — removed hardcoded GA4/Facebook Pixel/ecommerce setup tools in favor of generic `create_tag`
- Tightened dependency bounds: `mcp>=1.23.0` (CVE fixes), `google-api-python-client>=2.100.0`

### Fixed
- Custom event trigger template used `{{Event}}` instead of correct `{{_event}}` built-in variable
- `GTMClient.create_trigger` put filters under `filter` instead of `customEventFilter`
- `_run()` helper now returns `{}` on None API responses instead of crashing
- Credential file path no longer logged at INFO level
- `publish_version` response filtered to prevent metadata leakage

### Security
- All GTM ID parameters validated as numeric-only strings
- Batch operations capped at 50 items to prevent resource exhaustion
- Sanitized credential path logging
- Bumped MCP SDK to >=1.23.0 (CVE-2025-66416, CVE-2025-53366)
