# Proofrun Reference Guide

This document provides in-depth technical references for Proofrun configuration models, assertions, extraction engines, daemon lifecycle internals, and production deployments.

---

## 1. Complete Configuration Reference

A Proofrun monitoring file begins with `version: "1.0"`.

```yaml
version: "1.0" # Required; strictly "1.0"

global: # Optional defaults inherited by scenarios
  base_url: "https://api.example.com"
  timeout_seconds: 10 # Default: 10.0; ceiling in seconds (> 0)
  headers:
    Accept: "application/json"
  interval_seconds: 60 # Default: 60; daemon schedule interval
  retries: 0 # Default: 0; maximum 10
  retry_delay_seconds: 1 # Default: 1.0; 0 to 300 seconds
  failure_threshold: 1 # Default: 1; consecutive failures before FAILING
  recovery_threshold: 1 # Default: 1; consecutive passes before HEALTHY

scenarios: # List of multi-step test workflows (names must be unique)
  - name: "Authenticated Order Flow"
    base_url: "https://staging.example.com" # Overrides global.base_url
    interval_seconds: 30 # Overrides global.interval_seconds
    retries: 2
    retry_delay_seconds: 1.5
    failure_threshold: 3
    recovery_threshold: 2
    steps:
      - name: "Authenticate and acquire token"
        request:
          method: POST # GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
          path: /auth/login
          headers:
            Content-Type: "application/json"
          params: {}
          json:
            username: "admin"
            password: "${env.SERVICE_PASSWORD}"
          timeout: 5 # Overrides scenario/global timeout
        expect:
          status: 200 # Required; integer or list of integers (100–599)
          max_latency_ms: 1000 # Optional latency ceiling in ms
          headers:
            Content-Type: "application/json"
          schema: # Inline JSON Schema or path to a schema file
            type: object
            required: [token]
            properties:
              token:
                type: string
        extract:
          auth_token: "$.token" # JSONPath expression
```

---

## 2. Assertion Execution & Rules

During execution, assertions are evaluated in strict deterministic order:

1. **HTTP Status Codes**: `status` accepts a single integer (`200`) or list of valid codes (`[200, 201]`).
2. **Latency Ceiling**: `max_latency_ms` evaluates total request latency (including TLS handshake and headers).
3. **Response Headers**: Exact-value matching on response headers (case-insensitive keys). Values for sensitive headers (`Authorization`, `Cookie`, `Token`, `Key`, `Secret`, `Session`, `Password`) are suppressed from failure messages.
4. **JSON Body Validation**: Parsed when `schema` or `extract` is present. Rejects non-JSON response bodies.
5. **JSON Schema**: Pre-compiled AOT via `fastjsonschema`.
6. **Variable Extraction**: Extracts dynamic JSON values via JSONPath for subsequent requests.

Execution stops at the first failing step.

---

## 3. Variables & Dynamic Extraction

- **JSONPath Extraction**: If an expression matches multiple items, the first match wins. If no match is found, the step fails immediately.
- **Interpolation Scope**: Runtime variables `${var}` are interpolated in `path`, `headers`, `params`, and `json` bodies (both keys and values). They are **not** interpolated in `expect`, `extract`, or `base_url`.
- **Type Preservation**: An exact reference (`"${order_id}"`) preserves the underlying scalar type (integer, float, boolean). Mixed strings (`"order-${order_id}"`) cast to strings.
- **Built-in Generators**:
  - `${$uuid}`: Generates a new v4 UUID string.
  - `${$timestamp}`: Unix epoch in integer seconds.
  - `${$timestamp_ms}`: Unix epoch in integer milliseconds.
  - `${$iso_timestamp}`: UTC ISO-8601 string (e.g. `2026-01-31T12:00:00Z`).
  - `${$random_int}`: Pseudo-random integer between 1000 and 9999.

---

## 4. Retries & Health Thresholds

### Retries vs. Thresholds:
- **Retries** operate at the scenario level. If any step fails, the **entire scenario** is re-executed with a fresh HTTP client and execution context up to `retries` times.
  > **Note on Side Effects:** For scenarios containing non-idempotent mutation steps (e.g., creating resources), prefer `retries: 0` and rely on `failure_threshold`.
- **Thresholds** track consecutive final outcomes in daemon mode:
  - `failure_threshold`: Consecutive failed runs before the scenario transitions to `FAILING`.
  - `recovery_threshold`: Consecutive passing runs before returning to `HEALTHY`.

---

## 5. Daemon Architecture & Observability

In daemon mode (`--daemon`):
- Each scenario runs on an independent asyncio task with ±15% scheduled jitter.
- Scenarios never overlap with themselves. A slow run does not delay another scenario.
- Configuration edits to the YAML file trigger an automatic live reload without restarting the process.
- **Observability Server**: Serves standard text exposition metrics on `--metrics-port <PORT>`. Binds to `127.0.0.1` by default; binding to `0.0.0.0` requires `--allow-remote-metrics`.
- **Metrics Exposed**:
  - `proofrun_scenario_up`: Gauge (`1` for `HEALTHY`, `0` for `FAILING`).
  - `proofrun_scenario_runs_total`: Counter of total runs completed.
  - `proofrun_scenario_failures_total`: Counter of runs failing after retries.
  - `proofrun_scenario_duration_seconds`: Gauge of the latest scenario duration.
  - `proofrun_scenario_last_success_timestamp_seconds`: Timestamp of last pass.
  - `proofrun_scenario_last_failure_timestamp_seconds`: Timestamp of last failure.

---

## 6. Systemd & Deployment Reference

Example unit file template:

```ini
[Unit]
Description=Proofrun Synthetic Monitoring Daemon
After=network.target

[Service]
Type=simple
User=proofrun
Group=proofrun
EnvironmentFile=/etc/proofrun/proofrun.env
ExecStart=/opt/proofrun/bin/proofrun /etc/proofrun/monitors.yaml --daemon --metrics-port 9464
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

