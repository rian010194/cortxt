---
name: bvc-spec
description: Behaviour Validation Contract (BVC) specification schema and built-in contracts
category: software-development
tags: [bvc, contract, validation, monitoring, observability, sla]
version: 0.1.0
---

# BVC Specification

## BVC Schema (JSON Schema)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BehaviourValidationContract",
  "type": "object",
  "required": ["contract", "metadata"],
  "properties": {
    "contract": {
      "type": "object",
      "required": ["name", "version", "description", "expectation", "measurement", "thresholds", "labels", "alerting", "remediation", "validity"],
      "properties": {
        "name": {"type": "string", "pattern": "^[a-z0-9-]+$"},
        "version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
        "description": {"type": "string", "minLength": 10},
        "expectation": {"type": "string", "minLength": 20},
        "measurement": {
          "type": "object",
          "required": ["source", "query", "unit", "sample_window", "evaluation_interval"],
          "properties": {
            "source": {"enum": ["prometheus", "grafana", "custom", "logs", "github"]},
            "query": {"type": "string", "minLength": 1},
            "unit": {"type": "string"},
            "sample_window": {"type": "string", "pattern": "^\\d+[smhd]$"},
            "evaluation_interval": {"type": "string", "pattern": "^\\d+[smhd]$"},
            "custom_endpoint": {"type": ["string", "null"], "format": "uri"},
            "custom_method": {"type": ["string", "null"], "enum": ["GET", "POST"]},
            "custom_headers": {"type": ["object", "null"]},
            "custom_body": {"type": ["object", "null"]}
          }
        },
        "thresholds": {
          "type": "object",
          "properties": {
            "warn": {"type": ["number", "null"]},
            "fail": {"type": ["number", "null"]},
            "critical": {"type": ["number", "null"]}
          },
          "minProperties": 1
        },
        "labels": {
          "type": "object",
          "required": ["service", "team", "severity"],
          "properties": {
            "service": {"type": "string"},
            "team": {"type": "string"},
            "severity": {"enum": ["low", "medium", "high", "critical"]},
            "owner": {"type": ["string", "null"]},
            "runbook": {"type": ["string", "null"], "format": "uri"}
          }
        },
        "alerting": {
          "type": "object",
          "required": ["on", "channels", "cooldown"],
          "properties": {
            "on": {"enum": ["warn", "fail", "critical"]},
            "channels": {"type": "array", "items": {"enum": ["buzz", "github", "webhook", "email", "slack", "pagerduty"]}, "minItems": 1},
            "cooldown": {"type": "string", "pattern": "^\\d+[smhd]$"},
            "escalation": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["after", "channel", "message"],
                "properties": {
                  "after": {"type": "string", "pattern": "^\\d+[smhd]$"},
                  "channel": {"enum": ["buzz", "github", "webhook", "email", "slack", "pagerduty"]},
                  "message": {"type": "string"}
                }
              }
            }
          }
        },
        "remediation": {
          "type": "object",
          "required": ["runbook", "auto_mitigation"],
          "properties": {
            "runbook": {"type": "string", "format": "uri"},
            "auto_mitigation": {"type": "boolean"},
            "mitigation_script": {"type": ["string", "null"]}
          }
        },
        "validity": {
          "type": "object",
          "required": ["starts_at", "expires_at", "environments"],
          "properties": {
            "starts_at": {"type": "string", "format": "date-time"},
            "expires_at": {"type": ["string", "null"], "format": "date-time"},
            "environments": {"type": "array", "items": {"enum": ["development", "staging", "production"]}, "minItems": 1}
          }
        }
      }
    },
    "metadata": {
      "type": "object",
      "required": ["created_by", "created_at", "approved_by", "approved_at"],
      "properties": {
        "created_by": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "approved_by": {"type": "string"},
        "approved_at": {"type": "string", "format": "date-time"},
        "changelog": {"type": "array", "items": {"type": "string"}}
      }
    }
  }
}
```

## Built-in Contracts (5)

### 1. Service Availability
**File:** `contracts/bvc/service-availability.yaml`
```yaml
contract:
  name: "service-availability"
  version: "1.0.0"
  description: "Service responds to health checks above threshold"
  expectation: "Service health endpoint returns 200 OK > 99.9% of the time over 5m window"
  measurement:
    source: "prometheus"
    query: 'avg_over_time(up{job=~".+"}[5m])'
    unit: "ratio"
    sample_window: "5m"
    evaluation_interval: "1m"
  thresholds:
    warn: 0.9995
    fail: 0.999
    critical: 0.995
  labels:
    service: "platform"
    team: "platform"
    severity: "critical"
    runbook: "https://wiki.cortxt.io/runbooks/service-availability"
  alerting:
    on: "fail"
    channels: ["buzz", "github"]
    cooldown: "15m"
    escalation:
      - after: "30m"
        channel: "buzz"
        message: "ESCALATION: Service availability < 99.9% for 30min"
  remediation:
    runbook: "https://wiki.cortxt.io/runbooks/service-availability"
    auto_mitigation: false
  validity:
    starts_at: "2026-08-01T00:00:00Z"
    expires_at: null
    environments: ["production", "staging"]
metadata:
  created_by: "platform-team"
  created_at: "2026-08-03T00:00:00Z"
  approved_by: "rikard"
  approved_at: "2026-08-03T00:00:00Z"
  changelog: ["Initial version"]
```

### 2. API Error Rate
**File:** `contracts/bvc/api-error-rate.yaml`
```yaml
contract:
  name: "api-error-rate"
  version: "1.0.0"
  description: "API 5xx error rate below threshold"
  expectation: "5xx error rate < 0.1% for all API endpoints over 5m window"
  measurement:
    source: "prometheus"
    query: |
      sum(rate(http_requests_total{status=~"5.."}[5m])) 
      / sum(rate(http_requests_total[5m]))
    unit: "ratio"
    sample_window: "5m"
    evaluation_interval: "1m"
  thresholds:
    warn: 0.0005
    fail: 0.001
    critical: 0.005
  labels:
    service: "api"
    team: "platform"
    severity: "high"
    runbook: "https://wiki.cortxt.io/runbooks/api-error-rate"
  alerting:
    on: "fail"
    channels: ["buzz", "github"]
    cooldown: "10m"
    escalation:
      - after: "15m"
        channel: "buzz"
        message: "ESCALATION: API error rate > 0.1% for 15min"
  remediation:
    runbook: "https://wiki.cortxt.io/runbooks/api-error-rate"
    auto_mitigation: false
  validity:
    starts_at: "2026-08-01T00:00:00Z"
    expires_at: null
    environments: ["production", "staging"]
metadata:
  created_by: "platform-team"
  created_at: "2026-08-03T00:00:00Z"
  approved_by: "rikard"
  approved_at: "2026-08-03T00:00:00Z"
  changelog: ["Initial version"]
```

### 3. API Latency P95
**File:** `contracts/bvc/api-latency-p95.yaml`
```yaml
contract:
  name: "api-latency-p95"
  version: "1.0.0"
  description: "API p95 latency under normal load"
  expectation: "p95 latency < 500ms for /api/v1/* endpoints over 5m window"
  measurement:
    source: "prometheus"
    query: |
      histogram_quantile(0.95, 
        sum(rate(http_request_duration_seconds_bucket{job="api",handler=~"/api/v1/.*"}[5m])) by (le)
      )
    unit: "seconds"
    sample_window: "5m"
    evaluation_interval: "1m"
  thresholds:
    warn: 0.4
    fail: 0.5
    critical: 1.0
  labels:
    service: "api"
    team: "platform"
    severity: "high"
    runbook: "https://wiki.cortxt.io/runbooks/api-latency"
  alerting:
    on: "fail"
    channels: ["buzz", "github"]
    cooldown: "15m"
    escalation:
      - after: "30m"
        channel: "buzz"
        message: "ESCALATION: API p95 latency > 500ms for 30min"
  remediation:
    runbook: "https://wiki.cortxt.io/runbooks/api-latency"
    auto_mitigation: false
  validity:
    starts_at: "2026-08-01T00:00:00Z"
    expires_at: null
    environments: ["production", "staging"]
metadata:
  created_by: "platform-team"
  created_at: "2026-08-03T00:00:00Z"
  approved_by: "rikard"
  approved_at: "2026-08-03T00:00:00Z"
  changelog: ["Initial version"]
```

### 4. Daily LLM Cost Guardrail
**File:** `contracts/bvc/daily-llm-cost.yaml`
```yaml
contract:
  name: "daily-llm-cost"
  version: "1.0.0"
  description: "Daily LLM API cost within budget"
  expectation: "Daily LLM cost < $50 across all providers"
  measurement:
    source: "custom"
    custom_endpoint: "https://api.openrouter.ai/v1/usage?date=today"
    custom_method: "GET"
    custom_headers:
      Authorization: "Bearer ${OPENROUTER_API_KEY}"
    query: "total_cost_usd"
    unit: "USD"
    sample_window: "24h"
    evaluation_interval: "1h"
  thresholds:
    warn: 35
    fail: 50
    critical: 75
  labels:
    service: "llm-gateway"
    team: "platform"
    severity: "high"
    runbook: "https://wiki.cortxt.io/runbooks/llm-cost"
  alerting:
    on: "fail"
    channels: ["buzz", "github"]
    cooldown: "1h"
    escalation:
      - after: "2h"
        channel: "buzz"
        message: "ESCALATION: Daily LLM cost > $50 for 2h"
  remediation:
    runbook: "https://wiki.cortxt.io/runbooks/llm-cost"
    auto_mitigation: false
  validity:
    starts_at: "2026-08-01T00:00:00Z"
    expires_at: null
    environments: ["production"]
metadata:
  created_by: "platform-team"
  created_at: "2026-08-03T00:00:00Z"
  approved_by: "rikard"
  approved_at: "2026-08-03T00:00:00Z"
  changelog: ["Initial version"]
```

### 5. Deployment Success Rate
**File:** `contracts/bvc/deployment-success-rate.yaml`
```yaml
contract:
  name: "deployment-success-rate"
  version: "1.0.0"
  description: "Recent deployments succeed above threshold"
  expectation: "Last 10 production deployments > 90% success rate"
  measurement:
    source: "github"
    query: "repos/owner/repo/deployments?environment=production&per_page=10"
    unit: "ratio"
    sample_window: "10d"
    evaluation_interval: "1h"
  thresholds:
    warn: 0.95
    fail: 0.90
    critical: 0.80
  labels:
    service: "deployment"
    team: "platform"
    severity: "high"
    runbook: "https://wiki.cortxt.io/runbooks/deployment-success"
  alerting:
    on: "fail"
    channels: ["buzz", "github"]
    cooldown: "30m"
    escalation:
      - after: "1h"
        channel: "buzz"
        message: "ESCALATION: Deployment success rate < 90% for 1h"
  remediation:
    runbook: "https://wiki.cortxt.io/runbooks/deployment-success"
    auto_mitigation: false
  validity:
    starts_at: "2026-08-01T00:00:00Z"
    expires_at: null
    environments: ["production"]
metadata:
  created_by: "platform-team"
  created_at: "2026-08-03T00:00:00Z"
  approved_by: "rikard"
  approved_at: "2026-08-03T00:00:00Z"
  changelog: ["Initial version"]
```

## BVC Registry
**File:** `contracts/bvc/registry.yaml`
```yaml
contracts:
  - name: "service-availability"
    path: "contracts/bvc/service-availability.yaml"
    enabled: true
    schedule: "*/1 * * * *"
    owner: "platform-team"
  
  - name: "api-error-rate"
    path: "contracts/bvc/api-error-rate.yaml"
    enabled: true
    schedule: "*/1 * * * *"
    owner: "platform-team"
  
  - name: "api-latency-p95"
    path: "contracts/bvc/api-latency-p95.yaml"
    enabled: true
    schedule: "*/1 * * * *"
    owner: "platform-team"
  
  - name: "daily-llm-cost"
    path: "contracts/bvc/daily-llm-cost.yaml"
    enabled: true
    schedule: "0 * * * *"
    owner: "platform-team"
  
  - name: "deployment-success-rate"
    path: "contracts/bvc/deployment-success-rate.yaml"
    enabled: true
    schedule: "0 * * * *"
    owner: "platform-team"
```

## Version History
- 0.1.0: Initial BVC spec + 5 built-in contracts + registry