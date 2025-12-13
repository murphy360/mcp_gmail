# Gmail MCP Server

A Model Context Protocol (MCP) server for Gmail that provides natural language interaction with your inbox, daily summaries organized by category, and Home Assistant integration.

## Features

- 🔍 **Natural Language Search** - Search emails using plain language or Gmail query syntax
- 📊 **Category-Based Summaries** - Automatic categorization: Navy, Kids, Financial, Action Items
- 📱 **Home Assistant Integration** - REST API with sensors and notifications support
- 🐳 **Docker Support** - Easy deployment with Docker Compose
- 🔒 **Read-Only** - Currently read-only access to your inbox (safe!)

## Quick Start

### 1. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Gmail API**:
   - Navigate to "APIs & Services" → "Enable APIs"
   - Search for "Gmail API" and enable it
4. Create OAuth credentials:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Choose "Web application" (or "Desktop app")
   - For Web application, add `http://localhost:8080` to **Authorized redirect URIs**
   - Copy the Client ID and Client Secret

### 2. Configuration

```bash
# Clone and enter directory
cd mcp_gmail

# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
# GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
# GOOGLE_CLIENT_SECRET=your-client-secret
```

### 3. Initial Authentication (OAuth)

For the first-time setup, you need to authenticate with Google:

```bash
# Run the auth setup container
docker compose --profile setup run --rm gmail-mcp-auth
```

This will:
1. Open a browser window for Google authentication
2. Request permission to read your Gmail
3. Save the OAuth token to `./credentials/token.json`

### 4. Start the Server

```bash
# Start the main server
docker compose up -d

# Check logs
docker compose logs -f gmail-mcp
```

The REST API will be available at `http://localhost:8000`

## API Endpoints

### Health & Status

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check with auth status |
| `GET /api/stats` | Inbox statistics |

### Email Data (for Home Assistant Sensors)

| Endpoint | Description |
|----------|-------------|
| `GET /api/unread` | Total unread count |
| `GET /api/unread/categories` | Unread count per category |

### Summaries

| Endpoint | Description |
|----------|-------------|
| `GET /api/summary/daily` | Full daily summary (JSON) |
| `GET /api/summary/daily/text` | Daily summary as text |
| `GET /api/summary/category/{category}` | Category-specific summary |

### Home Assistant Integration

| Endpoint | Description |
|----------|-------------|
| `POST /api/webhook/trigger` | Send summary to HA webhook |

## Home Assistant Configuration

### REST Sensors

Add to your `configuration.yaml`:

```yaml
sensor:
  - platform: rest
    name: Gmail Unread
    resource: http://gmail-mcp:8000/api/unread
    value_template: "{{ value_json.unread }}"
    scan_interval: 300
    json_attributes:
      - timestamp

  - platform: rest
    name: Gmail Categories
    resource: http://gmail-mcp:8000/api/unread/categories
    value_template: "{{ value_json.total }}"
    scan_interval: 300
    json_attributes:
      - navy
      - kids
      - financial
      - action_required
      - other
```

### Template Sensors (from attributes)

```yaml
template:
  - sensor:
      - name: "Gmail Navy Unread"
        state: "{{ state_attr('sensor.gmail_categories', 'navy') }}"
        icon: mdi:anchor

      - name: "Gmail Kids Unread"
        state: "{{ state_attr('sensor.gmail_categories', 'kids') }}"
        icon: mdi:human-child

      - name: "Gmail Financial Unread"
        state: "{{ state_attr('sensor.gmail_categories', 'financial') }}"
        icon: mdi:currency-usd

      - name: "Gmail Action Required"
        state: "{{ state_attr('sensor.gmail_categories', 'action_required') }}"
        icon: mdi:alert-circle
```

### Automation: Daily Summary Notification

```yaml
automation:
  - alias: "Daily Email Summary"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: rest_command.gmail_summary
      - service: notify.mobile_app
        data:
          title: "📧 Email Summary"
          message: "{{ states('sensor.gmail_summary_text') }}"

rest_command:
  gmail_summary:
    url: "http://gmail-mcp:8000/api/webhook/trigger"
    method: POST
```

### Webhook Integration

Configure in your `.env`:

```bash
HA_WEBHOOK_URL=http://homeassistant.local:8123/api/webhook/gmail_summary
HA_LONG_LIVED_TOKEN=your-long-lived-access-token
```

Then create an automation triggered by the webhook:

```yaml
automation:
  - alias: "Gmail Webhook Handler"
    trigger:
      - platform: webhook
        webhook_id: gmail_summary
    action:
      - service: notify.mobile_app
        data:
          title: "📧 {{ trigger.json.event_type }}"
          message: "{{ trigger.json.data.text_summary }}"
```

## MCP Server Usage

The MCP server can be used with Claude Desktop, Home Assistant, or other MCP clients via SSE transport.

### Claude Desktop Configuration

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gmail": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://YOUR_SERVER_IP:8001/mcp/sse", "--allow-http"]
    }
  }
}
```

### Home Assistant MCP Integration

The server exposes SSE endpoints for MCP connections:
- `/mcp/sse` - Primary MCP SSE endpoint
- `/sse` - Alias endpoint for Home Assistant compatibility

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `gmail_search` | Search emails with query and optional filters |
| `gmail_get_email` | Get full email content by ID |
| `gmail_list_unread` | List unread emails with optional category filter |
| `gmail_daily_summary` | Generate categorized daily summary |
| `gmail_category_summary` | Summary for a specific category |
| `gmail_inbox_stats` | Current inbox statistics |
| `gmail_list_labels` | List all Gmail labels |
| `gmail_create_label` | Create a new Gmail label |
| `gmail_delete_label` | Delete a Gmail label |
| `gmail_get_categories` | Show configured categories |
| `gmail_mark_as_read_by_ids` | Mark specific emails as read by IDs |
| `gmail_mark_as_read_by_query` | Mark emails matching a query as read |
| `gmail_send_email` | Send an email (plain text or HTML) |
| `gmail_add_labels_to_messages` | Add labels to messages |
| `gmail_remove_labels_from_messages` | Remove labels from messages |

### Example Queries

- "What unread emails do I have about Navy?"
- "Show me my daily email summary"
- "Are there any action items I need to handle?"
- "Search for emails from the school"
- "What financial emails came in this week?"

## Customizing Categories

Edit `config/categories.yaml` to customize email categorization:

```yaml
categories:
  navy:
    name: "Navy / Military"
    priority: high
    matchers:
      senders:
        - "@navy.mil"
        - "@mail.mil"
      subjects:
        - "orders"
        - "deployment"
      labels:
        - "Navy"
```

### Matcher Types

- **senders**: Partial match on sender email/name
- **subjects**: Partial match on subject line
- **labels**: Exact match on Gmail labels

## Development

### Local Setup (without Docker)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install in development mode
pip install -e ".[dev]"

# Run authentication
mcp-gmail-auth

# Run the API server
mcp-gmail-api

# Or run the MCP server (stdio)
mcp-gmail
```

### Running Tests

```bash
pytest
pytest --cov=mcp_gmail
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Gmail MCP Server                         │
├─────────────────────────────────────────────────────────────┤
│  MCP Interface (stdio)          REST API (FastAPI)          │
│  └── Tools for Claude           └── Endpoints for HA        │
├─────────────────────────────────────────────────────────────┤
│                    Gmail Client                             │
│  ├── Search & List              ├── Categorization          │
│  └── OAuth2 Auth                └── Summary Generation      │
├─────────────────────────────────────────────────────────────┤
│                    Gmail API                                │
│  └── google-api-python-client                               │
└─────────────────────────────────────────────────────────────┘
```

## Roadmap

- [x] Read-only email access
- [x] Category-based summaries
- [x] Home Assistant REST API
- [x] Docker deployment
- [x] Email sending
- [x] Gmail labels management (create, delete, add to messages, remove from messages)
- [x] Mark emails as read
- [x] SSE transport with session isolation
- [x] Gemini-compatible tool schemas
- [ ] Scheduled summary notifications
- [ ] IMAP fallback option

## License

MIT License

## Troubleshooting

### OAuth Token Expired

```bash
# Re-run authentication
docker compose --profile setup run --rm gmail-mcp-auth
```

### Container Won't Start

Check that credentials exist:
```bash
ls -la credentials/
# Should contain token.json
```

### Home Assistant Can't Connect

Ensure the container is on the same Docker network or use the host IP:
```yaml
resource: http://192.168.1.100:8000/api/unread
```
