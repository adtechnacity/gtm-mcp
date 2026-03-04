# Google Tag Manager MCP Server

An MCP server that exposes Google Tag Manager API v2 as tools for AI agents like Claude. Manage tags, triggers, variables, consent settings, and publishing through natural language.

## Features

- **21 MCP tools** covering discovery, CRUD, consent management, batch operations, and publishing
- **OAuth2 authentication** with automatic token refresh
- **Template builder** for generating GTM component JSON locally
- **Batch operations** for bulk consent updates and variable creation

## Setup

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

### 2. Google Cloud Console Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Tag Manager API** under "APIs & Services" > "Library"
4. Go to "APIs & Services" > "Credentials"
5. Click "Create Credentials" > "OAuth 2.0 Client IDs"
6. Choose "Desktop application"
7. Download the JSON file and save it as `credentials.json` in this directory

### 3. Configure Your MCP Client

Add the server to your MCP client config (Claude Desktop, Claude Code, etc.):

```json
{
  "mcpServers": {
    "gtm": {
      "command": "uv",
      "args": ["run", "python", "/path/to/gtm-mcp/fastmcp_gtm_server.py"],
      "env": {
        "GTM_CREDENTIALS_FILE": "/path/to/gtm-mcp/credentials.json",
        "GTM_TOKEN_FILE": "/path/to/gtm-mcp/token.json"
      }
    }
  }
}
```

Or using the installed entry point:

```json
{
  "mcpServers": {
    "gtm": {
      "command": "mcp-gtm-server",
      "env": {
        "GTM_CREDENTIALS_FILE": "/path/to/credentials.json",
        "GTM_TOKEN_FILE": "/path/to/token.json"
      }
    }
  }
}
```

## Available Tools (21)

### Discovery
- `test_gtm_connection` — Verify OAuth2 credentials
- `list_gtm_accounts` — List all accessible GTM accounts
- `list_gtm_containers` — List containers in an account
- `list_gtm_workspaces` — List workspaces in a container

### Reading
- `list_gtm_tags` — List all tags with consent settings
- `list_gtm_triggers` — List all triggers with filters
- `list_gtm_variables` — List all variables
- `get_gtm_tag` — Get full tag details by ID

### Creating
- `create_ga4_setup` — Full GA4 setup (config tag + events + triggers + variables)
- `create_facebook_pixel_setup` — Facebook Pixel base tag + triggers
- `create_complete_ecommerce_setup` — GA4 + FB Pixel + conversions + form/click tracking
- `create_datalayer_variable` — Create a single Data Layer Variable
- `create_datalayer_variables_batch` — Create multiple Data Layer Variables
- `create_trigger` — Create a custom event trigger

### Modifying
- `update_tag_consent_settings` — Set consent config for one tag
- `update_tags_consent_settings_batch` — Set consent config for multiple tags
- `add_firing_trigger_to_tags_batch` — Add a trigger to multiple tags

### Deleting
- `delete_gtm_variable` — Delete a variable from workspace

### Publishing
- `publish_gtm_container` — Create version from workspace and publish

### Templates (Local Only)
- `generate_ga4_template` — Generate GA4 tag JSON without API calls

## Usage Examples

```
# Discover your GTM setup
List my GTM accounts, then show containers for account 123456

# Set up GA4 tracking
Create a complete GA4 setup with measurement ID G-XXXXXXXXXX in account 123456, container 7890123

# Audit consent settings
List all tags in my container and show which ones are missing consent configuration

# Bulk update consent
Set ad_storage and analytics_storage consent requirements on tags 1, 2, 3, 4, 5

# Full ecommerce setup
Create complete ecommerce tracking with GA4 G-XXXXXXXXXX and Facebook Pixel 123456789
```

## Running the Server

```bash
# Using the convenience script
./run_server.sh

# Or manually with uv
uv run python fastmcp_gtm_server.py
```

## File Structure

```
gtm-mcp/
├── fastmcp_gtm_server.py  # MCP server (21 tools)
├── gtm_client_fixed.py    # GTM API client with OAuth2
├── gtm_components.py      # Template builder (no API calls)
├── pyproject.toml          # Project config & dependencies
├── requirements.txt        # pip dependencies
├── run_server.sh           # Launch script
├── AGENTS.md               # AI agent reference & full API coverage
├── LICENSE                 # MIT
└── README.md               # This file
```

## Authentication

On first run, the server opens a browser window for OAuth2 authentication. Grant the required permissions (`tagmanager.edit.containers` and `tagmanager.publish`). The token is saved to `token.json` for subsequent runs.

## AI Agent Reference

See [AGENTS.md](AGENTS.md) for:
- Full GTM API v2 endpoint reference (105 methods across 18 resource families)
- Implementation status of each endpoint
- Common workflow patterns
- Priority list for future implementation

## License

MIT — see [LICENSE](LICENSE)
