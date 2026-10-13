<div align="center">

# Proofrun

**Write an API workflow in YAML. Run it locally, in CI, or as a monitor that only alerts when health changes.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/Kishan-Thanki/proofrun/actions/workflows/ci.yaml/badge.svg)](https://github.com/Kishan-Thanki/proofrun/actions/workflows/ci.yaml)
[![PyPI](https://img.shields.io/pypi/v/proofrun)](https://pypi.org/project/proofrun/)
[![Downloads](https://static.pepy.tech/badge/proofrun)](https://pepy.tech/project/proofrun)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/Kishan-Thanki/proofrun/blob/main/LICENSE)

</div>

---

Most monitors tell you an endpoint returned `200`. Proofrun tells you whether the
_journey_ works: log in, take the token from the response, use it on the next
request, and check what comes back.

When something breaks, you see exactly which step failed and why:

<div align="center">
  <img src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/demo-fail.svg" alt="Proofrun reporting a failed step in a login-then-fetch scenario" width="860">
</div>

And when everything is fine:

<div align="center">
  <img src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/demo-pass.svg" alt="Proofrun reporting a passing scenario" width="860">
</div>

**YAML in. HTTP checks out. No database, queue, or external service required.**

- **One file describes the workflow.** Scenarios live in Git next to your code.
- **Multi-step.** Values extracted from one response feed the next request.
- **Secrets stay out of Git.** Reference environment variables with `${env.NAME}`.
- **Runs anywhere.** The same file runs locally, in CI (exit code `0` / `1`), in Docker, or as a daemon under systemd.
- **Quiet by design.** Retries and failure thresholds filter out blips, and you are alerted when health _changes_, not on every failed check.
- **Observable.** Optional metrics endpoint in the text format, one series set per scenario.

## Contents

- [Quickstart](#quickstart-30-seconds)
- [A realistic example](#a-realistic-example-log-in-then-use-the-token)
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

Or with pipx, or use the [Docker image](#docker):

```bash
pipx install proofrun
```

> Proofrun uses [`uvloop`](https://github.com/MagicStack/uvloop) for a faster event
> loop where it is available. On Windows, where `uvloop` does not install, it
> falls back to the standard `asyncio` loop. CI runs on Linux only.

**2. Create `health.yaml`:**

```yaml
version: "1.0"

global:
  base_url: "https://jsonplaceholder.typicode.com"

scenarios:
  - name: "Public API is up"
    steps:
      - name: "GET /posts/1"
        request:
          method: GET
          path: /posts/1
        expect:
          status: 200
          max_latency_ms: 2000
```

**3. Run it:**

```bash
proofrun health.yaml
```

That's it. Swap in your own `base_url` and paths. Add `--daemon` to keep it
running.

## A realistic example: log in, then use the token

This is the scenario from the screenshots above. It logs in, extracts the
access token with JSONPath, sends it as a `Bearer` header on the next request,
extracts the user id from _that_ response, and uses it in the URL of the third.

```yaml
version: "1.0"

global:
  base_url: "http://127.0.0.1:8099"
  timeout_seconds: 5

scenarios:
  - name: "Login and fetch orders"
    steps:
      - name: "Log in"
        request:
          method: POST
          path: /login
          json:
            email: "demo@example.com"
            password: "demo-password"
        expect:
          status: 200
          max_latency_ms: 1000
        extract:
          token: "$.access_token" # saved as ${token}

      - name: "Fetch profile"
        request:
          method: GET
          path: /me
          headers:
            Authorization: "Bearer ${token}" # used here
        expect:
          status: 200
        extract:
          user_id: "$.id" # saved as ${user_id}

      - name: "Fetch orders"
        request:
          method: GET
          path: "/users/${user_id}/orders"
          headers:
            Authorization: "Bearer ${token}"
        expect:
          status: 200
          schema: # JSON Schema validation
            type: array
            minItems: 1
```

Steps run in order and stop at the first failure, so the report points at the
step that actually broke.

You can try this without any external service. The demo API lives in the
repository (it is not part of the pip package), so clone it first:

```bash
git clone https://github.com/Kishan-Thanki/proofrun.git
cd proofrun

# terminal 1: start the demo API (standard library only)
python3 scenarios/server.py

# terminal 2: run the scenario (passes, exit code 0)
proofrun scenarios/auth.yaml
```

Now break it on purpose. Restart the demo API with `--break`, which makes
`GET /me` return `500`, and run the same scenario again:

```bash
python3 scenarios/server.py --break
proofrun scenarios/auth.yaml # fails, exit code 1
```

The demo API also serves the other scenarios in `scenarios/`, so all of them run
offline: `profile.yaml` (header and schema checks), `chain.yaml` (chained
extraction and built-in variables), `crud.yaml` (multi-step create, read,
update, delete, plus a negative `404` check), and `resilient.yaml` (environment
variables, retries, thresholds, and per-scenario intervals; run it with
`DEMO_PASSWORD=demo-password`).

## Config reference

```yaml
version: "1.0" # required, only "1.0" is accepted

global: # optional defaults for every scenario/step
  base_url: "https://api.example.com"
  timeout_seconds: 10 # default 10, must be > 0
  headers: # merged into every request
    Accept: "application/json"
  interval_seconds: 60 # default 60
  retries: 0 # default 0, max 10
  retry_delay_seconds: 1 # default 1, 0 to 300
  failure_threshold: 1 # default 1
  recovery_threshold: 1 # default 1

scenarios: # required, list; names must be unique
  - name: "Scenario name" # required
    base_url: "https://staging.example.com" # optional, overrides global.base_url
    interval_seconds: 60 # optional, daemon mode only
    retries: 2 # optional, overrides the global value
    retry_delay_seconds: 1 # optional
    failure_threshold: 3 # optional
    recovery_threshold: 2 # optional
    steps: # required, run in order
      - name: "Step name" # required
        request:
          method: GET # required: GET POST PUT PATCH DELETE HEAD OPTIONS
          path: /things # required, joined onto base_url
          headers: {} # merged over global.headers
          params: {} # query string
          json: {} # JSON request body
          timeout: 5 # seconds, overrides global.timeout_seconds
        expect: # required
          status: 200 # required, int or list of ints
          max_latency_ms: 500
          headers: {}
          schema: {} # inline JSON Schema, or a file path
        extract: {} # variable name -> JSONPath
```

Rules the compiler enforces when the file is loaded:

- Every scenario needs a `base_url`, either its own or `global.base_url`.
Otherwise loading fails.
- `interval_seconds`, `retries`, `retry_delay_seconds`, `failure_threshold`, and
  `recovery_threshold` fall back to the `global` value when a scenario does not
  set them. A scenario value always wins, including `retries: 0`.
- Step `headers` are merged over `global.headers`; the step wins on conflicts.
- A step's `timeout` falls back to `global.timeout_seconds`.
- A `schema` given as a path is resolved relative to the config file first,
then relative to the current directory. It must be valid JSON.
- Scenario names must be unique, because the name identifies the scenario in
health tracking and metrics.
- A file needs at least one scenario, and every scenario at least one step.
- Unknown fields (for example a misspelled `max_latenc_ms`) and invalid values (bad
method, `timeout <= 0`, wrong `version`, a schema that fails to compile) are rejected
up front with an error that shows where the problem is. Nothing runs until the file
is valid.

## What you can assert

Each step's `expect` block supports:

| Assertion        | Example                                         | Notes                                                                  |
| ---------------- | ----------------------------------------------- | ---------------------------------------------------------------------- |
| `status`         | `status: 200` or `status: [200, 201]`           | Required. One code, or a non-empty list, each from 100 to 599. A list passes if the status matches any entry. |
| `max_latency_ms` | `max_latency_ms: 500`                           | Fails if the response took longer. Must be \> 0.                       |
| `headers`        | `headers: { Content-Type: "application/json" }` | Names are case-insensitive, values must match **exactly**. Values of sensitive headers (names containing auth, cookie, token, secret, key, password, or session) are hidden in failure messages. |
| `schema`         | inline JSON Schema, or a path to a file         | Validates the JSON response body. Fails if the body is not valid JSON. |

Checks run in this order and the step stops at the first one that fails:
status, latency, headers, JSON parsing, schema, extraction.

## Variables and extraction

A step can `extract` values from its JSON response with JSONPath. Later steps
use them as `${name}`.

```yaml
extract:
  token: "$.access_token"
  first_id: "$.items[0].id"
```

- If a path matches several values, the **first** match is used.
- If a path matches nothing, or the body is not JSON, the step fails.
- `${...}` is interpolated in `path`, `headers`, `params`, and the `json`
body (including dictionary keys). It is **not** interpolated in `expect`,
`extract`, or `base_url`.
- A value that is exactly one reference (`"${user_id}"`) keeps its type, so an
integer stays an integer in a JSON body. Mixed text (`"user-${user_id}"`) is
converted to a string.
- Referencing a variable that was never extracted fails the step with
`Missing required context variable`.
- Variables are scoped to one scenario run. They are not shared between
scenarios, between retries, or between daemon cycles.
- Names starting with `env.` are reserved for [environment variables](#environment-variables-and-secrets)
and cannot be used as extract names.

Built-in dynamic values work anywhere `${...}` does:

| Variable            | Value                                 |
| ------------------- | ------------------------------------- |
| `${$uuid}`          | Random UUID4 string                   |
| `${$timestamp}`     | Unix time in seconds                  |
| `${$timestamp_ms}`  | Unix time in milliseconds             |
| `${$iso_timestamp}` | UTC time, e.g. `2026-01-31T12:00:00Z` |
| `${$random_int}`    | Random integer from 1000 to 9999      |

Each reference generates a new value, so two `${$uuid}` in one payload differ.
To reuse one value, there is no built-in capture; extract it from a response
instead.

## Environment variables and secrets

Keep tokens and passwords out of the YAML. `${env.NAME}` is replaced by the value
of the environment variable `NAME` when the file is loaded:

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

- Works in any value (and dictionary key) of the file, including `base_url`.
- The result is always text. `"${env.PORT}"` gives `"8080"`, not the number `8080`.
- A missing variable is a configuration error that names the variable and where
  it is used, for example `Environment variable 'API_TOKEN' is not set (referenced at global.headers.Authorization)`.
  Nothing runs until it is fixed.
- Variables are read when the file is loaded, not on every request. In daemon
  mode, restart after changing the environment, or edit the file to reload it.
- Resolved values are never printed in configuration errors, which show only the
  field location and the problem. Proofrun does not otherwise redact response
  data, so avoid asserting on secrets.
- `${env.NAME}` is a separate namespace from run-time variables such as
  `${token}`, so the two never clash.

## Retries and thresholds

Two settings keep brief blips from turning into alerts. Both can be set under
`global` or per scenario.

**Retries** re-run a failed scenario before it counts as a failure:

```yaml
scenarios:
  - name: "Payments"
    retries: 2 # up to 3 attempts in total
    retry_delay_seconds: 2
```

- The **whole scenario** is re-run, not just the failed step, because earlier
  steps may have created state that later steps depend on.
- Every attempt starts with a fresh set of variables and a new HTTP client.
- Any failure is retried: connection errors, timeouts, and failed assertions.
- Only the final result counts. Output shows `Attempts: N` when more than one
  attempt was needed.
- Retries work in run-once mode too, which makes CI checks less flaky.

> **Retries repeat side effects.** A scenario that creates an order and then fails while
> fetching it will create a second order on the retry. Use `retries` for read-only
> checks. For scenarios that create or change data, set `retries: 0` and rely on
> `failure_threshold` instead.

**Thresholds** work across daemon cycles and count _consecutive_ runs:

```yaml
scenarios:
  - name: "Public API"
    failure_threshold: 3 # FAILING after 3 failed runs in a row
    recovery_threshold: 2 # HEALTHY again after 2 passing runs in a row
```

```text
Run 1: fail -> still HEALTHY (1 of 3)
Run 2: fail -> still HEALTHY (2 of 3)
Run 3: fail -> FAILING, alert sent
Run 4: pass -> still FAILING (1 of 2)
Run 5: pass -> HEALTHY, recovery alert sent
```

A pass resets the failure count and a failure resets the pass count. A scenario
that has never been seen before is `UNKNOWN`: it becomes `HEALTHY` on its first
pass, and `FAILING` after `failure_threshold` failed runs. The defaults of `1`
and `1` alert on the first failure and on the first recovery.

## Run it continuously

```bash
proofrun monitors/api.yaml --daemon
```

In daemon mode Proofrun runs your scenarios on a loop and tracks each one as
`HEALTHY` or `FAILING`.

- **Every scenario has its own schedule.** `interval_seconds` is per scenario,
  so a login check can run every 10 seconds and a report check every 5 minutes.
  All scenarios start immediately when the daemon starts.
- **A slow scenario never delays another**, and a scenario is never started while
  its previous run is still in progress, so runs of the same scenario do not
  overlap. If a run takes longer than its interval, the next one starts as soon
  as it finishes.
- **Jittered schedule.** Each interval varies by ±15% so checks don't all land on
  the same second.
- **Alerts on change, not on repetition.** A webhook fires when a scenario starts
  failing and again when it recovers. A scenario that stays down does not
  re-alert on every cycle.
- **Edit configs live.** Changes to the YAML are picked up within about a second,
  without a restart. Added scenarios start immediately and removed ones stop. If
  an edit is invalid, Proofrun keeps running the last working configuration and
  prints the error once.
- **Starts only with a valid config.** If the file is invalid when the daemon
  starts, it prints the error and exits with code 1 instead of idling.
- **Stops cleanly.** Ctrl+C or `SIGTERM` (what `systemctl stop` and `docker stop`
  send) cancels running scenarios, closes the metrics port, and exits with code 0.
- **Isolated runs.** Every run uses its own HTTP client, so cookies and
  connections are never shared between scenarios that run at the same time.

`--interval N` runs every scenario every N seconds and replaces each scenario's
`interval_seconds`.

Send alerts to any HTTP endpoint:

```bash
proofrun monitors/api.yaml --daemon --webhook-url https://<your_domain>/hooks/proofrun

# or

export PROOFRUN_WEBHOOK_URL=https://<your_domain>/hooks/proofrun
proofrun monitors/api.yaml --daemon
```

The webhook receives plain JSON via `POST`:

```json
{
  "event": "scenario_failed",
  "scenario": "Login and fetch orders",
  "previous_status": "HEALTHY",
  "status": "FAILING",
  "details": "- Fetch profile: Status code mismatch: expected one of [200], got 500"
}
```

`event` is `scenario_failed` or `scenario_recovered`. On recovery, `details` is
`"All steps passing."`.

**When alerts fire** (with the default thresholds of 1):

| Transition            | Alert                                            |
| --------------------- | ------------------------------------------------ |
| first run → passing   | none                                             |
| first run → failing   | `scenario_failed` (`previous_status: "UNKNOWN"`) |
| `HEALTHY` → `FAILING` | `scenario_failed`                                |
| `FAILING` → `FAILING` | none                                             |
| `FAILING` → `HEALTHY` | `scenario_recovered`                             |

With higher thresholds the same transitions apply, they just happen later.
Webhook delivery has a 5 second timeout. A failed delivery is printed with its
reason (an HTTP status, a timeout, or a connection error) and **not retried**. The
webhook URL is never printed, because it often contains a secret.

## Metrics

Proofrun can serve per-scenario metrics over HTTP in the text format, so any
scraper that reads it works.

```bash
proofrun monitors/api.yaml --daemon --metrics-port 9464
curl http://127.0.0.1:9464/metrics
```

| Metric                                             | Type    | Meaning                                                         |
| -------------------------------------------------- | ------- | --------------------------------------------------------------- |
| `proofrun_scenario_up`                             | gauge   | `1` when `HEALTHY`, `0` when `FAILING`. Absent while `UNKNOWN`. |
| `proofrun_scenario_runs_total`                     | counter | Scenario runs, counted after retries.                           |
| `proofrun_scenario_failures_total`                 | counter | Runs that failed after all retries.                             |
| `proofrun_scenario_duration_seconds`               | gauge   | Duration of the last run.                                       |
| `proofrun_scenario_last_success_timestamp_seconds` | gauge   | Unix time of the last passing run.                              |
| `proofrun_scenario_last_failure_timestamp_seconds` | gauge   | Unix time of the last failed run.                               |

```text
proofrun_scenario_up{scenario="Login and fetch orders"} 1
proofrun_scenario_runs_total{scenario="Login and fetch orders"} 42
```

- The only label is `scenario`. URLs, error messages, and response data are never
  used as labels.
- Series of scenarios removed from the config are dropped on the next config
  reload. Counters reset when the daemon restarts.
- `GET /health` returns `200 ok` while the Proofrun process is running. It says
  nothing about whether your scenarios are healthy; use `proofrun_scenario_up`
  for that.
- The server binds to **`127.0.0.1` by default** and has **no authentication or
  TLS**. `--metrics-host 0.0.0.0` exposes it to the network and prints a warning;
  only do that behind a firewall, a reverse proxy, or a container network.
- Example alert rule: `proofrun_scenario_up == 0`.

Metrics are only available in daemon mode.

## Validate a config

```bash
proofrun monitors/api.yaml --validate
```

Loads the file, resolves `${env.NAME}` references, validates everything, and
compiles JSON schemas, **without sending a single request**. It prints the
scenarios with their effective settings and exits `0`, or prints the problem and
exits `1`. Use it in pre-commit hooks and CI. Set the environment variables the
config references, because a missing one is an error.

## Use it in CI

Proofrun exits with `0` when every scenario passes and `1` when any fails, so it
works as a smoke test or a scheduled check. For example, with GitHub Actions:

```yaml
name: API check

on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:

jobs:
  proofrun:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install proofrun
      - run: proofrun monitors/api.yaml --validate
        env:
          API_TOKEN: ${{ secrets.API_TOKEN }}
      - run: proofrun monitors/api.yaml
        env:
          API_TOKEN: ${{ secrets.API_TOKEN }}
```

A failing check fails the workflow run, and GitHub notifies you the way it
notifies you about any failed workflow. Add `retries` to a scenario to keep
one-off network errors from failing the build.

Exit codes in run-once mode:

| Code | Meaning                                                           |
| ---- | ----------------------------------------------------------------- |
| `0`  | All scenarios passed (or `--validate` found no problems)          |
| `1`  | A scenario failed, or the config could not be loaded or validated |
| `2`  | Bad command-line usage, such as a config path that does not exist |

## Docker

Images are published to GitHub Container Registry for `linux/amd64` and
`linux/arm64`:

```bash
docker run --rm ghcr.io/kishan-thanki/proofrun --version

# run once
docker run --rm -v "$PWD/monitors:/monitors:ro" \
  -e API_TOKEN \
  ghcr.io/kishan-thanki/proofrun /monitors/api.yaml

# run as a monitor, with metrics published on the host's loopback only
docker run -d --name proofrun --restart unless-stopped \
  -v "$PWD/monitors:/monitors:ro" \
  -e API_TOKEN \
  -e PROOFRUN_WEBHOOK_URL \
  -e PROOFRUN_METRICS_PORT=9464 -e PROOFRUN_METRICS_HOST=0.0.0.0 \
  -p 127.0.0.1:9464:9464 \
  ghcr.io/kishan-thanki/proofrun /monitors/api.yaml --daemon
```

- Tags: `latest`, the exact version (`0.2.0`), and `major.minor` (`0.2`). The image is
  based on Alpine and is small.
- `docker stop` shuts the container down cleanly within a second or two.
- The container runs as an unprivileged user (uid `10001`). Mount your configs
  read-only.
- Inside a container the metrics server has to listen on `0.0.0.0` to be
  reachable; publish the port on `127.0.0.1` as above unless you protect it.
- The image has no built-in health check because metrics are optional. With
  `--metrics-port`, use `GET /health`. See [`deploy/docker-compose.yaml`](https://github.com/Kishan-Thanki/proofrun/blob/main/deploy/docker-compose.yaml) for a
  complete example with a health check, a read-only filesystem, and dropped
  capabilities.

## systemd

Ready-to-use files live in [`deploy/systemd/`](https://github.com/Kishan-Thanki/proofrun/tree/main/deploy/systemd): a hardened unit
(`proofrun.service`) and an environment file template (`proofrun.env.example`).

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

Secrets go in `/etc/proofrun/proofrun.env` (referenced from the YAML as
`${env.NAME}`), not in the unit or the config. The unit restarts the service on
failure and runs it as an unprivileged user with no capabilities and a read-only
view of the filesystem. Edits to `monitors.yaml` are picked up while it runs;
changes to the environment file need `sudo systemctl restart proofrun`. Run
`/opt/proofrun/bin/proofrun /etc/proofrun/monitors.yaml --validate` before
restarting, and review the unit's sandboxing with
`systemd-analyze security proofrun`.

## CLI

```bash
proofrun <config.yaml>                 # run once and exit (default)
proofrun <config.yaml> --once          # same, explicit
proofrun <config.yaml> --validate      # check the config, send no requests
proofrun <config.yaml> --daemon        # run continuously
proofrun <config.yaml> --daemon -i 30  # every scenario every 30 seconds
proofrun <config.yaml> --daemon --webhook-url <url>
proofrun <config.yaml> --daemon --metrics-port 9464
proofrun --version                     # or -v
python -m proofrun <config.yaml>       # equivalent to the proofrun command
```

| Option                | Description                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------- |
| `--once` / `--daemon` | Run once and exit (default), or loop until stopped with Ctrl+C.                             |
| `--validate`          | Check the configuration and exit. Cannot be combined with `--daemon`.                       |
| `--interval`, `-i`    | Daemon: run every scenario every N seconds, replacing each `interval_seconds`. Must be ≥ 1. |
| `--webhook-url`       | Daemon: alert destination. Also read from `PROOFRUN_WEBHOOK_URL`.                           |
| `--metrics-port`      | Daemon: serve metrics on this port (1 to 65535). Also `PROOFRUN_METRICS_PORT`.             |
| `--metrics-host`      | Address for the metrics server. Default `127.0.0.1`. Also `PROOFRUN_METRICS_HOST`.          |
| `--version`, `-v`     | Print the version and exit.                                                                 |
| `--install-completion`, `--show-completion` | Install, or print, shell completion for `proofrun`.                  |

Daemon-only options (`--interval`, `--webhook-url`, `--metrics-port`, `--metrics-host`)
given in run-once mode are ignored, with a warning.

## Behavior notes and limits

- **Failures stop the scenario.** Remaining steps are not run, and the report
shows only the steps that ran.
- **Cookies persist within a scenario run** (a session cookie from a login step is
sent on later steps) and are never shared with another run or scenario.
- **State is in memory.** Restarting the daemon resets health tracking, so a
scenario that is already down alerts again after a restart.
- **Webhooks and metrics are daemon-only.** Run-once mode does not track state.
- **JSON only for body checks.** `schema` and `extract` require a JSON response.
Status, latency, and header checks work with any response.
- **No connection reuse between runs.** Each run opens its own connections, which
  is closer to what a real client experiences and keeps runs isolated.
- **Intervals are whole seconds**, at least 1.
- **Webhook delivery is not retried.** A failure is printed and the daemon keeps
  running.
- **Failure messages can contain response data.** Only the values of sensitive headers
  are hidden. Do not assert on secrets, and treat console output and alert payloads as
  non-confidential.
- **One config file per process.** Run several daemons for several files.
- **Configuration errors are shown on the console.** They are not sent as alerts.

## License

Proofrun is licensed under the [MIT License](https://github.com/Kishan-Thanki/proofrun/blob/main/LICENSE).
See the [changelog](https://github.com/Kishan-Thanki/proofrun/blob/main/CHANGELOG.md) for what changed in each release.
