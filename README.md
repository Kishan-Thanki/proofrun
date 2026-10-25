<div align="center">

# Proofrun

**Test API responses and workflows—not just status codes. Run locally, in CI, or continuously.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/Kishan-Thanki/proofrun/actions/workflows/ci.yaml/badge.svg)](https://github.com/Kishan-Thanki/proofrun/actions/workflows/ci.yaml)
[![PyPI](https://img.shields.io/pypi/v/proofrun)](https://pypi.org/project/proofrun/)
[![Downloads](https://static.pepy.tech/badge/proofrun)](https://pepy.tech/project/proofrun)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/Kishan-Thanki/proofrun/blob/main/LICENSE)

</div>

---

An endpoint can return `200 OK` while its response is missing a field your application needs. And even when individual endpoints behave as expected, a workflow can fail when one request depends on data returned by another.

<div align="center">
  <img src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/assets/proofrun-thumbnail.svg" alt="Proofrun reporting a passing scenario" width="860">
</div>

**Proofrun lets you test both individual API responses and complete multi-step workflows** using readable YAML scenarios.

- Check one request's status, latency, headers, and JSON response schema.
- Extract values from a response and reuse them in later requests.
- See which step failed and why when a scenario stops.
- Reuse the same scenario locally, in CI, or continuously in daemon mode.

<div align="center">
  <img
    src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/assets/demo-fail.svg"
    alt="Proofrun reporting a failed step in a multi-step scenario"
    width="860"
  >
</div>

A passing run looks like this:

<div align="center">
  <img
    src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/assets/demo-pass.svg"
    alt="Proofrun reporting a passing scenario"
    width="860"
  >
</div>

**YAML in. API checks out. No database, queue, or external monitoring service required.**

- **Single-request checks.** Validate status codes, response time, headers, and JSON Schema—even when an endpoint returns `200`.
- **Multi-step workflows.** Extract values from a response and use them in subsequent paths, headers, query parameters, or JSON bodies.
- **Configuration in Git.** Keep scenario definitions alongside your application code.
- **Run it where you work.** Use the same file locally, in CI, in Docker, or as a daemon under systemd.
- **Health-aware alerts.** Retries and failure/recovery thresholds help reduce noise; daemon webhooks fire on health-state transitions.
- **Optional metrics.** Expose Prometheus-compatible metrics in daemon mode.

API testing and synthetic monitoring tools already exist; Proofrun does not claim otherwise. Its focus is a lightweight, self-hosted CLI that covers both individual response validation and dependent API workflows without requiring a larger platform.

## Contents

- [Quickstart](#quickstart-30-seconds)
- [Check a single API response](#check-a-single-api-response)
- [Test a multi-step workflow](#test-a-multi-step-workflow)
- [Config reference](#config-reference)
- [Assertions](#what-you-can-assert)
- [Variables and extraction](#variables-and-extraction)
- [Environment variables and secrets](#environment-variables-and-secrets)
- [Retries and thresholds](#retries-and-thresholds)
- [Run it continuously](#run-it-continuously)
- [Metrics](#metrics)
- [Validate a config](#validate-a-config)
- [Use it in CI](#use-it-in-ci)
- [Docker](#docker)
- [systemd](#systemd)
- [CLI](#cli)
- [Behavior notes and limits](#behavior-notes-and-limits)

## Quickstart (30 seconds)

**1. Install** (Python 3.11+):

```bash
pip install proofrun
```
> Proofrun uses [`uvloop`](https://github.com/MagicStack/uvloop) where it is available. On platforms where `uvloop` does not install, it falls back to the standard `asyncio` event loop.

**2. Create `health.yaml`:**

```yaml
version: "1.0"

global:
  base_url: "https://jsonplaceholder.typicode.com"

scenarios:
  - name: "Public API response matches its contract"
    steps:
      - name: "GET /posts/1"
        request:
          method: GET
          path: /posts/1
        expect:
          status: 200
          max_latency_ms: 2000
          schema:
            type: object
            required: [userId, id, title, body]
            properties:
              userId:
                type: integer
              id:
                type: integer
              title:
                type: string
              body:
                type: string
```

**3. Run it:**

```bash
proofrun health.yaml
```

This checks one API response—not just its status code, but also whether its JSON structure matches the schema. Replace the example `base_url` and path with your own API. Add `--daemon` to run scenarios continuously.

## Check a single API response

You do not need a chain of requests to use Proofrun. A scenario can contain one step that checks a single endpoint.

```yaml
version: "1.0"

global:
  base_url: "https://api.example.com"
  timeout_seconds: 5

scenarios:
  - name: "Get order details"
    steps:
      - name: "GET /orders/4821"
        request:
          method: GET
          path: /orders/4821
        expect:
          status: 200
          max_latency_ms: 500
          schema:
            type: object
            required: [id, status, total]
            properties:
              id:
                type: integer
              status:
                type: string
              total:
                type: number
```

This can catch a response that returns `200 OK` but no longer contains a required field or returns a field with the wrong type. JSON Schema only validates the constraints you define; it does not automatically prove every business rule.

## Test a multi-step workflow

A workflow becomes useful when one request depends on the result of another. For example, create an order, extract its ID, then retrieve that specific order.

```yaml
version: "1.0"

global:
  base_url: "https://api.example.com"
  timeout_seconds: 5

scenarios:
  - name: "Create and retrieve an order"
    steps:
      - name: "Create order"
        request:
          method: POST
          path: /orders
          json:
            product_id: 123
            quantity: 1
        expect:
          status: 201
          schema:
            type: object
            required: [id]
            properties:
              id:
                type: integer
        extract:
          order_id: "$.id"

      - name: "Retrieve the created order"
        request:
          method: GET
          path: "/orders/${order_id}"
        expect:
          status: 200
          schema:
            type: object
            required: [id, status]
            properties:
              id:
                type: integer
              status:
                type: string
```

This is an illustrative example; adapt the paths, request body, and expected schemas to your API. Proofrun executes steps in order and stops at the first failure, so the report identifies the step where the scenario broke.

For a runnable local example, clone the repository and start its demo API:

```bash
git clone https://github.com/Kishan-Thanki/proofrun.git
cd proofrun

# Terminal 1: start the demo API
python3 scenarios/server.py

# Terminal 2: run the authentication example
proofrun scenarios/auth.yaml
```

To demonstrate a failure, stop the demo API and restart it with `--break`, which makes `GET /me` return `500`:

```bash
python3 scenarios/server.py --break
proofrun scenarios/auth.yaml  # expected scenario failure, exit code 1
```

The demo API also supports the other scenario files in `scenarios/`: `profile.yaml` (header and schema checks), `chain.yaml` (chained extraction and built-in variables), `crud.yaml` (create/read/update/delete and a negative `404` check), and `resilient.yaml` (environment variables, retries, thresholds, and per-scenario intervals). To run `resilient.yaml` with the demo password, use:

```bash
DEMO_PASSWORD=demo-password proofrun scenarios/resilient.yaml
```

## Config reference

```yaml
version: "1.0" # required; only "1.0" is accepted

global: # optional defaults
  base_url: "https://api.example.com"
  timeout_seconds: 10 # default 10; must be > 0
  headers:
    Accept: "application/json"
  interval_seconds: 60 # default 60; daemon mode
  retries: 0 # default 0; maximum 10
  retry_delay_seconds: 1 # default 1; allowed range 0–300
  failure_threshold: 1 # default 1
  recovery_threshold: 1 # default 1

scenarios: # required; names must be unique
  - name: "Scenario name" # required
    base_url: "https://staging.example.com" # optional; overrides global.base_url
    interval_seconds: 60 # optional; daemon mode
    retries: 2 # optional; overrides global value
    retry_delay_seconds: 1 # optional
    failure_threshold: 3 # optional
    recovery_threshold: 2 # optional
    steps: # required; run in order
      - name: "Step name" # required
        request:
          method: GET # GET POST PUT PATCH DELETE HEAD OPTIONS
          path: /things # required; joined onto base_url
          headers: {} # merged over global.headers
          params: {} # query parameters
          json: {} # JSON request body
          timeout: 5 # seconds; overrides global.timeout_seconds
        expect: # required
          status: 200 # required; integer or list of integers
          max_latency_ms: 500
          headers: {}
          schema: {} # inline JSON Schema or path to a JSON Schema file
        extract: {} # variable name -> JSONPath, from a JSON response
```

Rules enforced when the configuration is loaded:

- Every scenario needs `base_url`, either on the scenario or under `global`.
- Scenario settings fall back to global values when omitted. An explicit scenario value wins, including `retries: 0`.
- Step headers are merged over global headers; step values win on conflicts.
- A step's `timeout` falls back to `global.timeout_seconds`.
- A schema file path is resolved relative to the YAML file first, then relative to the current working directory. The schema file must contain valid JSON Schema.
- Scenario names must be unique because names identify scenarios in health tracking and metrics.
- At least one scenario and at least one step per scenario are required.
- Unknown fields and invalid values (such as a bad method, `timeout <= 0`, unsupported version, or schema that cannot be compiled) are rejected before requests run.

## What you can assert

Each step's `expect` block supports the following:

| Assertion | Example | Behavior |
| --- | --- | --- |
| `status` | `status: 200` or `status: [200, 201]` | Required. A single code or non-empty list; each code must be 100–599. A list passes if any value matches. |
| `max_latency_ms` | `max_latency_ms: 500` | Fails if the response exceeds the maximum. Must be positive. |
| `headers` | `headers: { Content-Type: "application/json" }` | Header names are case-insensitive; values must match exactly. |
| `schema` | Inline JSON Schema or file path | Validates the JSON response body; fails if the body is not valid JSON or does not satisfy the schema. |

Checks occur in this order: status, latency, headers, JSON parsing when required, schema, and extraction. Execution stops at the first failed step.

Sensitive-looking header values are hidden in relevant failure messages. This redaction is limited: do not assume response bodies, extracted variables, or arbitrary error text are comprehensively redacted.

## Variables and extraction

A step can extract values from its JSON response using JSONPath. Later steps can reference those values as `${name}`.

```yaml
extract:
  token: "$.access_token"
  first_id: "$.items[0].id"
```

- If a JSONPath expression matches several values, the first match is used.
- If it matches nothing, or the response body is not JSON, the step fails.
- Runtime variables can be interpolated in `path`, `headers`, `params`, and the `json` body, including dictionary keys. They are **not** interpolated in `expect`, `extract`, or `base_url`.
- A value that is exactly one reference (`"${user_id}"`) retains its type, so an integer remains an integer in a JSON body. Mixed text such as `"user-${user_id}"` becomes a string.
- Referencing a variable that has not been created fails the step with a missing-context-variable error.
- Variables are scoped to one scenario attempt. They are not shared between scenarios, retries, or daemon cycles.
- Names beginning with `env.` are reserved for environment references and cannot be extract names.

Built-in dynamic values work anywhere runtime interpolation is supported:

| Variable | Value |
| --- | --- |
| `${$uuid}` | Random UUID4 string |
| `${$timestamp}` | Unix time in seconds |
| `${$timestamp_ms}` | Unix time in milliseconds |
| `${$iso_timestamp}` | UTC timestamp, for example `2026-01-31T12:00:00Z` |
| `${$random_int}` | Random integer from 1000 to 9999 |

Each built-in reference generates a new value. To reuse one generated value, capture it in a variable through the workflow rather than referencing the built-in repeatedly.

## Environment variables and secrets

Use `${env.NAME}` to supply configuration values from the process environment instead of hardcoding them in YAML. Environment references are resolved when the configuration is loaded.

```yaml
global:
  base_url: "${env.API_BASE_URL}"
  headers:
    Authorization: "Bearer ${env.API_TOKEN}"
```

```bash
export API_BASE_URL=https://api.example.com
export API_TOKEN=...
proofrun monitors/api.yaml
```

- Environment references work in YAML values and dictionary keys, including `base_url`.
- The resolved value is text. For example, `${env.PORT}` produces a string such as `"8080"`, not the integer `8080`.
- A missing variable is a configuration error that identifies the variable and its location; nothing runs until it is fixed.
- Values are resolved when the file loads, not before every request. In daemon mode, changing an environment variable alone does not trigger reload; restart the process to apply environment changes.
- Configuration errors avoid echoing resolved secret values. This does not guarantee universal output redaction: response bodies, extracted values, and other error text may still contain sensitive data.
- `${env.NAME}` is distinct from runtime variables such as `${token}`.

## Retries and thresholds

Retries and health thresholds address different problems. Both can be configured globally or per scenario.

**Retries** rerun a failed scenario before its final result is counted:

```yaml
scenarios:
  - name: "Read-only payment status check"
    retries: 2 # up to 3 attempts in total
    retry_delay_seconds: 2
```

- The **whole scenario** is retried, not only the failed step.
- Every attempt gets a fresh variable context and HTTP client.
- Failed assertions, timeouts, connection errors, and other step failures can trigger a retry.
- Only the final result counts toward health. Output reports the number of attempts when more than one was needed.
- Retries also apply in run-once mode, including CI.

> **Retries can repeat side effects.** If a scenario creates an order and later fails, a retry can create another order. Prefer retries for read-only checks or APIs designed for safe repetition. For workflows with non-idempotent side effects, use `retries: 0` unless repeat execution is safe.

**Failure and recovery thresholds** count consecutive final scenario outcomes in daemon mode:

```yaml
scenarios:
  - name: "Public API"
    failure_threshold: 3 # enter FAILING after 3 failed runs in a row
    recovery_threshold: 2 # return to HEALTHY after 2 passing runs in a row
```

```text
Run 1: fail -> still not FAILING (1 of 3)
Run 2: fail -> still not FAILING (2 of 3)
Run 3: fail -> FAILING; failure alert sent
Run 4: pass -> still FAILING (1 of 2)
Run 5: pass -> HEALTHY; recovery alert sent
```

A pass resets the failure count; a failure resets the pass count. A new scenario begins in `UNKNOWN`. With default thresholds of `1` and `1`, its first failed run transitions to `FAILING`; its first successful run transitions to `HEALTHY` without a notification. A recovery webhook is sent for `FAILING -> HEALTHY`.

## Run it continuously

```bash
proofrun monitors/api.yaml --daemon
```

In daemon mode, Proofrun schedules scenarios, tracks health, can send webhook alerts, and can expose metrics.

- **Per-scenario schedules.** Each scenario can have its own `interval_seconds`; all scenarios start immediately when the daemon starts.
- **No overlapping run of the same scenario.** A scenario is not started while its previous run is in progress. Other scenarios can run independently.
- **Jitter.** Scheduled intervals vary by approximately ±15% to avoid synchronized bursts.
- **Transition-based notifications.** A scenario that remains failing does not send the same alert every cycle. A recovery alert is sent when the health state returns to `HEALTHY`.
- **Live config reload.** Changes to the main YAML file are picked up without restarting. Added scenarios start and removed scenarios stop. If an edit is invalid, Proofrun keeps the last-known-good configuration and reports the error. A config that is invalid at startup prevents the daemon from starting.
- **Reload limits.** Changes to environment variables or a referenced schema file alone do not trigger reload; restart or change the main config as appropriate.
- **Clean shutdown.** Ctrl+C or `SIGTERM` cancels running work and closes the metrics server.
- **Isolated runs.** Each scenario attempt uses its own HTTP client and variable context. Cookies may persist across sequential steps in that attempt, but are not shared between separate runs.

`--interval N` overrides each scenario's configured interval in daemon mode. It must be at least one second.

Send alerts to an HTTP endpoint:

```bash
proofrun monitors/api.yaml --daemon --webhook-url https://example.com/hooks/proofrun

# Or use the environment variable:
export PROOFRUN_WEBHOOK_URL=https://example.com/hooks/proofrun
proofrun monitors/api.yaml --daemon
```

The webhook receives JSON via `POST`, for example:

```json
{
  "event": "scenario_failed",
  "scenario": "Create and retrieve an order",
  "previous_status": "HEALTHY",
  "status": "FAILING",
  "details": "- Retrieve the created order: Status code mismatch: expected one of [200], got 500"
}
```

`event` is `scenario_failed` or `scenario_recovered`. On recovery, `details` is `"All steps passing."`.

| Transition | Notification |
| --- | --- |
| `UNKNOWN -> HEALTHY` | None |
| `UNKNOWN -> FAILING` | `scenario_failed` |
| `HEALTHY -> FAILING` | `scenario_failed` |
| `FAILING -> FAILING` | None |
| `FAILING -> HEALTHY` | `scenario_recovered` |

Transitions happen after the configured thresholds are met. Webhook delivery has a five-second timeout. A failed delivery is logged and is not retried; the webhook URL is not printed in delivery errors.

## Metrics

Proofrun can serve per-scenario metrics over HTTP in Prometheus text exposition format:

```bash
proofrun monitors/api.yaml --daemon --metrics-port 9464
curl http://127.0.0.1:9464/metrics
```

| Metric | Type | Meaning |
| --- | --- | --- |
| `proofrun_scenario_up` | Gauge | `1` when `HEALTHY`, `0` when `FAILING`; absent while `UNKNOWN`. |
| `proofrun_scenario_runs_total` | Counter | Scenario runs counted after retries. |
| `proofrun_scenario_failures_total` | Counter | Scenario runs that failed after retries were exhausted. |
| `proofrun_scenario_duration_seconds` | Gauge | Duration of the most recent scenario run. |
| `proofrun_scenario_last_success_timestamp_seconds` | Gauge | Unix timestamp of the last passing run. |
| `proofrun_scenario_last_failure_timestamp_seconds` | Gauge | Unix timestamp of the last failing run. |

Example:

```text
proofrun_scenario_up{scenario="Create and retrieve an order"} 1
proofrun_scenario_runs_total{scenario="Create and retrieve an order"} 42
```

- The only label is `scenario`; URLs, error messages, and response bodies are not labels.
- Series for removed scenarios are dropped on configuration reload. Counters and health state reset when the daemon restarts.
- `GET /health` reports whether the Proofrun metrics server is alive; it does **not** indicate whether monitored scenarios are healthy. Use `proofrun_scenario_up` for scenario health.
- The server binds to `127.0.0.1` by default and has no authentication or TLS. Binding to `0.0.0.0` exposes it on the container/network interface; protect it with a firewall, reverse proxy, or trusted network.
- An example alert condition is `proofrun_scenario_up == 0`.

Metrics are available only in daemon mode. Duration is scenario-level, not a separate per-step latency histogram.

## Validate a config

```bash
proofrun monitors/api.yaml --validate
```

This loads the file, resolves `${env.NAME}` references, validates the configuration, and compiles JSON Schemas **without sending requests**. It exits `0` when valid and `1` when a configuration load or validation error occurs. Set environment variables referenced by the config; a missing variable is an error.

## Use it in CI

Proofrun returns `0` when all scenarios pass and `1` when a scenario fails or the configuration cannot be loaded or validated. CLI usage errors return `2`.

Treat scenario files as executable configuration: they can make authenticated HTTP requests to configured endpoints. Do not run untrusted scenario changes with privileged credentials.

A safer GitHub Actions pattern is to validate configuration on pull requests without making API requests, then run authenticated checks after changes reach the trusted `main` branch.

```yaml
name: API checks

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  validate:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"

      - run: python -m pip install proofrun

      - name: Validate configuration without sending requests
        run: proofrun monitors/api.yaml --validate
        env:
          # Placeholder only; never expose real credentials to this job.
          API_TOKEN: validation-placeholder

  run-api-checks:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    environment: api-checks
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"

      - run: python -m pip install proofrun

      - name: Run API scenarios
        run: proofrun monitors/api.yaml
        env:
          API_TOKEN: ${{ secrets.API_TOKEN }}
```

Run against a test or staging API, and keep credentials in your CI secret store. A failed scenario fails the job. Use retries judiciously, particularly for workflows that have side effects.

Run-once exit codes:

| Code | Meaning |
| --- | --- |
| `0` | All scenarios passed, or config validation succeeded. |
| `1` | A scenario failed or config loading/validation failed. |
| `2` | CLI usage error, such as a config path that does not exist. |

## Docker

Images are published to GitHub Container Registry:

```bash
docker run --rm ghcr.io/kishan-thanki/proofrun --version

# Run once
docker run --rm \
  -v "$PWD/monitors:/monitors:ro" \
  -e API_TOKEN \
  ghcr.io/kishan-thanki/proofrun /monitors/api.yaml

# Run as a monitor; publish metrics on host loopback only
docker run -d --name proofrun --restart unless-stopped \
  -v "$PWD/monitors:/monitors:ro" \
  -e API_TOKEN \
  -e PROOFRUN_WEBHOOK_URL \
  -e PROOFRUN_METRICS_PORT=9464 \
  -e PROOFRUN_METRICS_HOST=0.0.0.0 \
  -p 127.0.0.1:9464:9464 \
  ghcr.io/kishan-thanki/proofrun /monitors/api.yaml --daemon --allow-remote-metrics
```

- The image runs as an unprivileged user (UID `10001`). Mount config files read-only.
- Inside a container, the metrics server must listen on `0.0.0.0` to be reachable through a published port. Publishing to `127.0.0.1` on the host limits exposure.
- Metrics are optional, so the image does not require the metrics endpoint for basic run-once use.
- See [`deploy/docker-compose.yaml`](https://github.com/Kishan-Thanki/proofrun/blob/main/deploy/docker-compose.yaml) for a Compose example using a read-only filesystem, dropped capabilities, and a health check.

### Verify a published image

Release images are signed by digest using Cosign keyless signing. With Cosign installed, set `RELEASE_TAG` to the exact release tag and `IMAGE_DIGEST` to the registry digest (`sha256:...`):

```bash
RELEASE_TAG="vX.Y.Z"
IMAGE_DIGEST="sha256:..."
cosign verify --certificate-identity "https://github.com/Kishan-Thanki/proofrun/.github/workflows/release.yaml@refs/tags/${RELEASE_TAG}" --certificate-oidc-issuer "https://token.actions.githubusercontent.com" "ghcr.io/kishan-thanki/proofrun@${IMAGE_DIGEST}"
```

Use the immutable digest for verification rather than a mutable image tag. Replace both placeholders with values from the release.


## systemd

Ready-to-use files live in [`deploy/systemd/`](https://github.com/Kishan-Thanki/proofrun/tree/main/deploy/systemd): a service unit and an environment file template.

A typical installation looks like this; adjust ownership and paths to your host:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin proofrun
sudo python3 -m venv /opt/proofrun
sudo /opt/proofrun/bin/pip install proofrun
sudo install -d /etc/proofrun
sudo cp monitors.yaml /etc/proofrun/monitors.yaml
sudo install -m 600 deploy/systemd/proofrun.env.example /etc/proofrun/proofrun.env
sudo cp deploy/systemd/proofrun.service /etc/systemd/system/proofrun.service
sudo systemctl daemon-reload
sudo systemctl enable --now proofrun
journalctl -u proofrun -f
```

Put credentials in `/etc/proofrun/proofrun.env`, not directly in the unit or scenario YAML. Review the example unit and confirm its paths, user, and environment-file settings for your host. Changing the environment file requires a service restart; edits to the main YAML are picked up by the running daemon.

## CLI

```bash
proofrun <config.yaml>                 # run once (default)
proofrun <config.yaml> --once          # same, explicit
proofrun <config.yaml> --validate      # validate config; send no requests
proofrun <config.yaml> --daemon        # run continuously
proofrun <config.yaml> --daemon -i 30  # override all scenario intervals
proofrun <config.yaml> --daemon --webhook-url <url>
proofrun <config.yaml> --daemon --metrics-port 9464
proofrun <config.yaml> --daemon --metrics-port 9464 --metrics-host 0.0.0.0 --allow-remote-metrics
proofrun --version                     # or -v
python -m proofrun <config.yaml>       # equivalent module entry point
```

| Option | Description |
| --- | --- |
| `--once` / `--daemon` | Run once and exit (default), or run continuously until stopped. |
| `--validate` | Validate configuration without sending requests; cannot be combined with `--daemon`. |
| `--interval`, `-i` | Daemon-only: replace each scenario interval with this number of seconds. Must be at least `1`. |
| `--webhook-url` | Daemon-only webhook destination; also configurable with `PROOFRUN_WEBHOOK_URL`. |
| `--metrics-port` | Daemon-only metrics port (`1`–`65535`); also configurable with `PROOFRUN_METRICS_PORT`. |
| `--metrics-host` | Daemon-only metrics bind address; defaults to `127.0.0.1`. Also configurable with `PROOFRUN_METRICS_HOST`. |
| `--allow-remote-metrics` | Daemon-only: explicitly permits unauthenticated metrics on a non-loopback address. |
| `--version`, `-v` | Print version and exit. |
| `--install-completion`, `--show-completion` | Install or print shell completion. |

Daemon-only options explicitly supplied on the command line in run-once mode are rejected with a clear error. Setting their environment variables alone does not force daemon mode or prevent a run-once check.

## Behavior notes and limits

- **A failed step stops the scenario.** Remaining steps do not run; the report identifies the steps that ran and the failure.
- **Single-request checks are supported.** A scenario can contain one step for status, latency, header, and schema validation.
- **Body extraction and schema validation require JSON.** Status, latency, and header checks can be used without parsing a JSON body.
- **Cookies persist within one scenario attempt** so a session established in an earlier step can be used by a later step. Cookies and clients are not shared between independent runs.
- **Retries rerun the entire scenario.** Side effects may repeat; set retries according to the safety of the workflow.
- **State is in memory.** Restarting the daemon resets health tracking and metrics, so a failing scenario may alert again after restart.
- **Webhooks and metrics are daemon-only.** Run-once mode reports results and exit status but does not track health transitions or serve metrics.
- **Webhook delivery is not retried.** A delivery failure is logged and the daemon continues.
- **Secret redaction is limited.** Sensitive-looking response header values are masked in relevant failures, but arbitrary response bodies, extracted variables, and error messages are not comprehensively redacted. Treat output and alert payloads as potentially non-confidential.
- **Only the main YAML file is watched for reload.** Changes to referenced schema files or environment variables alone do not trigger a reload.
- **The metrics `/health` endpoint is process health, not target API health.** Use `proofrun_scenario_up` to inspect scenario state.
- **One config file per process.** Run separate processes if you need to monitor separate files.

## License

Proofrun is licensed under the [MIT License](https://github.com/Kishan-Thanki/proofrun/blob/main/LICENSE). See the [changelog](https://github.com/Kishan-Thanki/proofrun/blob/main/CHANGELOG.md) for release history.
