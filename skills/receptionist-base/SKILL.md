---
name: "receptionist-base"
version: "0.1.0"
maturity: "experimental"
category: "software-development"
description: "Generic base skill for system receptionists providing CRUD, auth, rate-limiting, caching, and error handling"
author: "Cortxt"
license: "MIT"
---

# Receptionist Base Skill

## Purpose
Provides a generic base class for all system receptionists. Handles common concerns:
- Authentication via credential-manager
- CRUD operations with retry logic
- Rate limiting with token bucket
- Caching with TTL
- Error taxonomy and retry policies
- Observability (metrics, traces, structured logs)

## Interface Contract
- **Input**: ReceptionistRequest (action, resource, params, context)
- **Output**: ReceptionistResponse<T> (success, data, metadata, links, errors)
- **Errors**: ReceptionistError with codes and recovery hints
- **OpenAPI**: receptionist-base.openapi.yaml

## Capabilities

### Auth
- `get_token()` - Retrieve valid token from credential-manager
- `refresh()` - Refresh expired token
- `validate()` - Validate token format and expiry
- `rotate()` - Rotate credentials

### CRUD
- `create(resource, params)` - Create new resource
- `read(resource, id)` - Read resource by ID
- `update(resource, id, params, mode)` - Update resource (replace|merge)
- `delete(resource, id, force)` - Delete resource

### Search/Query
- `query(resource, filter, sorts, pagination)` - Query with filtering
- `get_by_id(resource, id)` - Get single resource
- `count(resource, filter)` - Count matching resources

### Webhook
- `register(events, target_url, secret)` - Register webhook
- `verify(payload, signature)` - Verify webhook signature
- `handle(payload, headers)` - Handle incoming webhook

### Rate Limit
- `check(cost)` - Check if request fits in budget
- `reserve(cost, ttl)` - Reserve rate limit tokens
- `wait_if_needed(cost)` - Block until tokens available

### Cache
- `get(key)` - Get cached value
- `set(key, value, ttl)` - Set cached value
- `invalidate(key|pattern)` - Invalidate cache entries
- `invalidate_tag(tag)` - Invalidate by tag

### Error Handling
- `retry_with_backoff(fn, attempts, base_delay, max_delay)` - Retry with exponential backoff
- `classify_error(error)` - Classify as transient/permanent
- `should_retry(error)` - Determine if error is retryable

## Configuration
```yaml
system: string
base_url: string
auth:
  type: "bearer" | "api_key" | "oauth2" | "file_access" | "none"
  token_path: string
  refresh_endpoint?: string
  scopes?: string[]
  credential_manager_ref: string
rate_limits:
  default: {requests: number, window_seconds: number}
  per_endpoint: {endpoint: {requests, window_seconds}}
cache:
  default_ttl_ms: number
  per_resource: {resource: ttl_ms}
timeouts:
  default_ms: number
  per_action: {action: ms}
retry:
  max_attempts: 3
  base_delay_ms: 500
  max_delay_ms: 10000
observability:
  log_requests: true
  log_responses: false
  trace_header: "x-trace-id"
  metrics_prefix: "receptionist"
```

## Dependencies
- credential-manager (>=0.1.0, required)

## Error Taxonomy

### Transient (retryable)
- RATE_LIMITED
- UPSTREAM_ERROR
- TIMEOUT
- AUTH_EXPIRED

### Permanent (non-retryable)
- VALIDATION_ERROR
- PERMISSION_DENIED
- NOT_FOUND
- VAULT_NOT_FOUND

### Retry Policy
- Transient: max 3 attempts, exponential backoff (500ms base, 10s max)
- Permanent: max 0 attempts (no retry)

## Observability
- Metrics: request.total, request.duration_ms, request.success, request.error, rate_limit.remaining, cache.hit, cache.miss
- Traces: enabled (W3C traceparent)
- Logs: structured-json