# Changelog

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
