---
name: "receptionist-notion"
version: "0.1.0"
maturity: "experimental"
category: "software-development"
description: "Receptionist for Notion workspace - CRUD, search, webhook for databases, pages, blocks, comments, users"
author: "Cortxt"
license: "MIT"
---

# Receptionist Notion Skill

## Purpose
Provides a typed interface to Notion API for CRUD operations on databases, pages, blocks, comments, users, and search. All auth via credential-manager (bearer token type).

## Extends
- receptionist-base

## Interface Contract
- **Input**: ReceptionistRequest with Notion-specific actions/resources
- **Output**: ReceptionistResponse with Notion domain objects
- **Errors**: ReceptionistError with Notion-specific codes
- **OpenAPI**: receptionist-notion.openapi.yaml

## Resources & Actions

### Database
- `create(database, params)` - Create new database
- `read(database, id)` - Get database schema
- `update(database, id, params)` - Update database properties
- `delete(database, id)` - Archive database
- `query(database, filter, sorts, pagination)` - Query database entries

### Page
- `create(page, params)` - Create new page
- `read(page, id)` - Get page content + properties
- `update(page, id, params, mode)` - Update page (replace|merge properties)
- `delete(page, id)` - Archive page
- `query(page, filter, sorts, pagination)` - Search pages

### Block
- `create(block, params)` - Append blocks to page
- `read(block, id)` - Get block content
- `update(block, id, params)` - Update block
- `delete(block, id)` - Delete block
- `children(block, id, pagination)` - Get block children

### Comment
- `create(comment, params)` - Add comment to page/discussion
- `read(comment, id)` - Get comment
- `list(comment, page_id, pagination)` - List comments on page

### User
- `read(user, id)` - Get user info
- `list(user, pagination)` - List workspace users
- `me(user)` - Get current bot user

### Search
- `search(query, filter, sort, pagination)` - Search workspace

### Webhook
- `register(webhook, events, target_url, secret)` - Register webhook
- `verify(webhook, payload, signature)` - Verify webhook signature
- `handle(webhook, payload, headers)` - Handle webhook event

## Configuration
```yaml
system: "notion"
base_url: "https://api.notion.com/v1"
auth:
  type: "bearer"
  token_path: "notion/integration_token"
  credential_manager_ref: "credential-manager"
rate_limits:
  default: {requests: 90, window_seconds: 60}  # Notion limit: 3 req/s avg
  per_endpoint:
    databases: {requests: 30, window_seconds: 60}
    pages: {requests: 60, window_seconds: 60}
    blocks: {requests: 60, window_seconds: 60}
    search: {requests: 10, window_seconds: 60}
cache:
  default_ttl_ms: 300000  # 5 min
  per_resource:
    database: 600000
    page: 300000
    block: 300000
    user: 3600000
    search: 60000
timeouts:
  default_ms: 10000
  per_action:
    search: 15000
    query: 15000
observability:
  log_requests: true
  log_responses: false
  trace_header: "x-trace-id"
  metrics_prefix: "receptionist.notion"
```

## Dependencies
- receptionist-base (>=0.1.0, required)
- credential-manager (>=0.1.0, required)

## Error Taxonomy (extends base)

### Transient
- RATE_LIMITED
- UPSTREAM_ERROR
- TIMEOUT
- AUTH_EXPIRED

### Permanent
- VALIDATION_ERROR
- PERMISSION_DENIED
- NOT_FOUND
- VAULT_NOT_FOUND
- NOTION_UNAUTHORIZED
- NOTION_FORBIDDEN
- NOTION_RATE_LIMITED
- NOTION_VALIDATION_ERROR
- NOTION_CONFLICT

## Observability
- Metrics: request.total, request.duration_ms, request.success, request.error, rate_limit.remaining, cache.hit, cache.miss, notion.api_calls, notion.pages_created, notion.databases_queried
- Traces: enabled
- Logs: structured-json