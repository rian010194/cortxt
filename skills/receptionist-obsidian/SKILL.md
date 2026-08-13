---
name: "receptionist-obsidian"
version: "0.1.0"
maturity: "experimental"
category: "software-development"
description: "Receptionist for Obsidian vault - CRUD, search, webhook, frontmatter, dataview queries, templates"
author: "Cortxt"
license: "MIT"
---

# Receptionist Obsidian Skill

## Purpose
Provides a typed interface to an Obsidian vault for CRUD operations, search, frontmatter manipulation, dataview queries, and template rendering. All auth via credential-manager (file_access type).

## Extends
- receptionist-base

## Interface Contract
- **Input**: ReceptionistRequest with Obsidian-specific actions/resources
- **Output**: ReceptionistResponse with Obsidian domain objects
- **Errors**: ReceptionistError with Obsidian-specific codes
- **OpenAPI**: receptionist-obsidian.openapi.yaml

## Resources & Actions

### File
- `create(file, params)` - Create new markdown file with frontmatter
- `read(file, path)` - Read file content + parsed frontmatter
- `update(file, path, params, mode)` - Update file (replace|merge frontmatter)
- `delete(file, path, force)` - Delete file

### Folder
- `create(folder, params)` - Create folder
- `read(folder, path)` - List folder contents
- `delete(folder, path, force)` - Delete folder (recursive)

### Frontmatter
- `get(frontmatter, path, key)` - Get frontmatter value
- `set(frontmatter, path, key, value)` - Set frontmatter value
- `merge(frontmatter, path, params)` - Merge frontmatter
- `validate(frontmatter, path, schema)` - Validate against schema

### Link
- `get(link, path)` - Get all links from file
- `backlinks(link, path)` - Get backlinks to file
- `broken(link)` - Find broken links

### Tag
- `get(tag, path)` - Get tags from file
- `search(tag, query)` - Search by tag

### Dataview Query
- `query(dataview_query, params)` - Execute DataviewJS/DQL query
- `render(dataview_query, params)` - Render query as table/list

### Template
- `render(template, params)` - Render template with params
- `create_from_template(template, params, target_path)` - Create file from template

### Search
- `search(file, query, options)` - Full-text search

### Webhook
- `register(webhook, events, target_url, secret)` - Register vault webhook
- `verify(webhook, payload, signature)` - Verify webhook
- `handle(webhook, payload, headers)` - Handle webhook event

## Configuration
```yaml
system: "obsidian"
base_url: ""  # Not used for file_access
auth:
  type: "file_access"
  vault_path: "/host/vault"  # Mounted in Pi container
  credential_manager_ref: "credential-manager"
rate_limits:
  default: {requests: 100, window_seconds: 60}
cache:
  default_ttl_ms: 300000  # 5 min
  per_resource:
    file: 60000
    folder: 300000
    dataview_query: 60000
timeouts:
  default_ms: 5000
  per_action:
    dataview_query: 15000
    search: 10000
observability:
  log_requests: true
  log_responses: false
  trace_header: "x-trace-id"
  metrics_prefix: "receptionist.obsidian"
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
- FILE_NOT_FOUND
- TEMPLATE_NOT_FOUND
- DATAVIEW_ERROR
- FRONTMATTER_PARSE_ERROR
- ENCODING_ERROR

## Observability
- Metrics: request.total, request.duration_ms, request.success, request.error, rate_limit.remaining, cache.hit, cache.miss, vault.files_read, vault.files_written, dataview.queries
- Traces: enabled
- Logs: structured-json