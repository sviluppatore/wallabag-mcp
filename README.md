# wallabag MCP
<p align="center">
  <a href="https://buymeacoffee.com/rusty4" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50">
  </a>
</p>



<!-- mcp-name: io.github.sviluppatore/wallabag-mcp -->

A Model Context Protocol (MCP) server for [wallabag](https://wallabag.org/), the open-source read-it-later service.

This server gives AI assistants a structured interface for common wallabag workflows:

- Verify connectivity and authentication with a tiny read-only health check
- List, filter, and page through saved articles
- Full-text search saved articles (wallabag 2.5+)
- Check whether a URL is already saved before re-adding it
- Fetch entry metadata or readable article text
- Export full entry content (txt, json, xml, csv)
- Save new URLs
- Archive/unarchive and star/unstar entries
- Reload/refetch article extraction
- Delete entries
- List, add, and remove tags
- List, create, update, and delete annotations

## Why this exists

wallabag is widely used in self-hosted setups, but its API is OAuth-based and awkward for general LLM tools. This MCP server wraps the important entry, tag, and annotation operations with an AI-friendly surface and documented parameters.

## Installation

```bash
pipx install git+https://github.com/sviluppatore/wallabag-mcp.git
```

Or from a checkout:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

The server reads configuration from environment variables:

| Variable | Required | Description |
|---|---:|---|
| `WALLABAG_BASE_URL` | Yes | Base URL of your wallabag instance, e.g. `https://app.wallabag.it` |
| `WALLABAG_ACCESS_TOKEN` | Optional | Existing OAuth access token; if set, password grant is skipped |
| `WALLABAG_REFRESH_TOKEN` | Optional | OAuth refresh token; used to renew expired access tokens before falling back to the password grant |
| `WALLABAG_CLIENT_ID` | Required unless access token is set | OAuth client id from wallabag's developer client page |
| `WALLABAG_CLIENT_SECRET` | Required unless access token is set | OAuth client secret |
| `WALLABAG_USERNAME` | Required unless access token is set | wallabag username |
| `WALLABAG_PASSWORD` | Required unless access token is set | wallabag password |
| `WALLABAG_TIMEOUT` | No | HTTP timeout in seconds, default `20` |

Create a wallabag API client from your wallabag instance under **Developer / API clients**. wallabag's official docs show the password grant against `/oauth/v2/token`.

## MCP client config

```json
{
  "mcpServers": {
    "wallabag": {
      "command": "wallabag-mcp",
      "env": {
        "WALLABAG_BASE_URL": "https://wallabag.example.com",
        "WALLABAG_CLIENT_ID": "your-client-id",
        "WALLABAG_CLIENT_SECRET": "your-client-secret",
        "WALLABAG_USERNAME": "your-username",
        "WALLABAG_PASSWORD": "your-password"
      }
    }
  }
}
```

## Tools

| Tool | Purpose |
|---|---|
| `wallabag_health_check` | Verify connectivity and authentication with a tiny read-only request |
| `wallabag_list_entries` | List entries with pagination and filters |
| `wallabag_search` | Full-text search entries (requires wallabag 2.5+) |
| `wallabag_entry_exists` | Check whether a URL is already saved |
| `wallabag_get_entry` | Fetch one entry, optionally with its readable text content |
| `wallabag_export_entry` | Export an entry's full content as txt, json, xml, or csv |
| `wallabag_add_entry` | Save a URL into wallabag |
| `wallabag_update_entry` | Update title, URL, archive/starred state, or tags |
| `wallabag_archive_entry` | Mark an entry archived/read |
| `wallabag_unarchive_entry` | Mark an entry unarchived/unread |
| `wallabag_star_entry` | Star/favourite an entry |
| `wallabag_unstar_entry` | Remove starred/favourite state |
| `wallabag_reload_entry` | Ask wallabag to refetch/reparse the original URL |
| `wallabag_delete_entry` | Delete an entry |
| `wallabag_list_tags` | List known tags |
| `wallabag_add_tags_to_entry` | Add comma-separated tags to an entry |
| `wallabag_remove_tag_from_entry` | Remove a tag from one entry without deleting it globally |
| `wallabag_delete_tag` | Delete a tag globally |
| `wallabag_list_annotations` | List annotations for an entry |
| `wallabag_create_annotation` | Create an annotation on quoted article text |
| `wallabag_update_annotation` | Update an annotation's text |
| `wallabag_delete_annotation` | Delete an annotation |

## Development and validation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest
python scripts/live_docs_test.py
```

`live_docs_test.py` validates wallabag's public API documentation and the hosted API docs page without needing account credentials; in CI it runs on a weekly schedule (or manual dispatch) rather than on every push, so external site hiccups don't block development. Mutation and authenticated request behaviours are covered with mocked HTTP tests.

## Safety

Write-capable tools mutate your read-it-later library. Keep OAuth secrets in environment variables or a secret manager, never in source control.
