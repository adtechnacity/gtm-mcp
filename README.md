# Google Tag Manager MCP Server

A Model Context Protocol (MCP) server that integrates Google Tag Manager with Claude, enabling automated GTM configuration and component creation through natural language prompts.

## Features

- **GTM API Integration**: Full Google Tag Manager API integration for creating and managing tags, triggers, and variables
- **Component Templates**: Pre-built templates for common tracking scenarios (GA4, Facebook Pixel, conversion tracking)
- **Workflow Automation**: Complete workflow creation for different site types (ecommerce, lead generation, content sites)
- **Claude Integration**: Natural language interface for GTM configuration through Claude

## Setup

### 1. Install Dependencies

#### Option A: Using uv (Recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Install dependencies
uv sync
```

#### Option B: Using pip

```bash
pip install -r requirements.txt
```

### 2. Google Cloud Console Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the Tag Manager API:
   - Go to "APIs & Services" > "Library"
   - Search for "Tag Manager API"
   - Click "Enable"

### 3. Create Service Account Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth 2.0 Client IDs"
3. Choose "Desktop application"
4. Download the JSON file and save it as `credentials.json` in this directory

### 4. Configure Claude

Add the MCP server configuration to your Claude config:

```json
{
  "mcpServers": {
    "gtm": {
      "command": "python",
      "args": ["/path/to/mcp-for-gtm/server.py"],
      "env": {
        "GTM_CREDENTIALS_FILE": "/path/to/mcp-for-gtm/credentials.json",
        "GTM_TOKEN_FILE": "/path/to/mcp-for-gtm/token.json"
      }
    }
  }
}
```

## Available Tools

### Basic GTM Operations

- **`create_gtm_tag`**: Create individual GTM tags
- **`create_gtm_trigger`**: Create GTM triggers  
- **`create_gtm_variable`**: Create GTM variables
- **`list_gtm_containers`**: List all containers for an account
- **`get_gtm_container`**: Get container details
- **`publish_gtm_version`**: Publish a container version

### Workflow Tools

- **`create_ga4_setup`**: Complete Google Analytics 4 setup with config tag and common events
- **`create_facebook_pixel_setup`**: Facebook Pixel tracking setup
- **`create_form_tracking`**: Form submission tracking setup
- **`generate_gtm_workflow`**: Generate complete workflows for different site types

## Usage Examples

### 1. Set up Google Analytics 4 tracking

```
Create a complete GA4 setup for my website with measurement ID G-XXXXXXXXXX in GTM account 123456 and container 7890123
```

### 2. Generate ecommerce tracking workflow

```
Generate a complete ecommerce tracking workflow with GA4 measurement ID G-XXXXXXXXXX and Facebook Pixel ID 123456789
```

### 3. Create form tracking

```
Set up form tracking for the contact form with selector #contact-form in my GTM container
```

### 4. Create custom components

```
Create a custom GTM tag for tracking video plays with the following parameters: event_name = "video_play", video_title = "{{Video Title}}", video_duration = "{{Video Duration}}"
```

## Workflow Types

The `generate_gtm_workflow` tool supports three main workflow types:

- **`ecommerce`**: Enhanced ecommerce tracking with purchase, cart, and product interaction events
- **`lead_generation`**: Form submissions, CTA clicks, and conversion tracking
- **`content_site`**: Content engagement, newsletter signups, and social sharing

## Authentication

On first run, the server will open a browser window for OAuth authentication. Grant the necessary permissions to access your GTM account. The authentication token will be saved for future use.

## File Structure

```
mcp-for-gtm/
├── server.py              # Main MCP server
├── gtm_client.py          # GTM API client
├── gtm_components.py      # Component templates and workflow builder
├── requirements.txt       # Python dependencies
├── config.json           # MCP server configuration
├── credentials.json      # Google OAuth credentials (you provide)
├── token.json           # Generated auth token (auto-created)
└── README.md           # This file
```

## Troubleshooting

### Authentication Issues
- Ensure `credentials.json` is properly configured from Google Cloud Console
- Check that Tag Manager API is enabled in your Google Cloud project
- Verify you have the necessary permissions in your GTM account

### Permission Errors
- Make sure your Google account has edit permissions for the GTM container
- Ensure the GTM account and container IDs are correct

### API Errors
- Check your GTM account and container IDs
- Verify that the workspace exists (default workspace ID is used)
- Check rate limits if you're making many requests

## Development

### Running Tests

```bash
# Using uv
uv run python test_server.py

# Or directly with python
python test_server.py
```

### Running the Server

```bash
# Using the convenience script
./run_server.sh

# Or manually with uv
uv run python server.py

# Or with system python
python server.py
```

### Development Dependencies

The project includes development dependencies for code quality:

```bash
# Format code with black
uv run black .

# Check with flake8
uv run flake8 .

# Type checking with mypy
uv run mypy .

# Run tests with pytest
uv run pytest
```

## Contributing

Feel free to submit issues and enhancement requests!