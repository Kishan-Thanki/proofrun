# Changelog

All notable changes to Proofrun are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Proofrun is below 1.0,
so a minor release can contain breaking changes; each one is listed under
**Breaking changes**.

## [0.2.0]

### Added

- **Environment variables.** `${env.NAME}` is resolved when a config file is
  loaded, in any value or key, including `base_url`. A missing variable is a
  configuration error that names the variable and where it is used.
- **Retries.** `retries` and `retry_delay_seconds` (per scenario or under
  `global`) re-run the whole scenario before a failure counts. Results show
  `Attempts: N`. Retries also work in run-once mode.
- **Thresholds.** `failure_threshold` and `recovery_threshold` count consecutive
  runs before a scenario becomes `FAILING` or recovers. The defaults (`1`, `1`)
  keep the previous behavior.
- **Per-scenario scheduling.** Every scenario runs on its own `interval_seconds`,
  with jitter. A slow scenario does not delay another, and a scenario never
  overlaps with itself. `interval_seconds` can also be set under `global`.
- **Metrics.** `--metrics-port` (and `--metrics-host`) serve
  `/metrics` and `/health` in daemon mode. Metrics: `proofrun_scenario_up`,
  `_runs_total`, `_failures_total`, `_duration_seconds`,
  `_last_success_timestamp_seconds`, `_last_failure_timestamp_seconds`. The only
  label is `scenario`. The server binds to loopback by default.
- **`--validate`.** Checks a configuration, including environment references,
  without sending requests.
- **Docker image** for `linux/amd64` and `linux/arm64`, published to
  `ghcr.io/kishan-thanki/proofrun` by the release pipeline (after the tests pass and
  the tag matches the package version), running as a non-root user.
- **Deployment examples:** a hardened systemd unit and environment file in
  `deploy/systemd/`, and `deploy/docker-compose.yaml`.
- `scenarios/resilient.yaml`, an offline example of the features above.
- A warning when `--webhook-url` or `--metrics-port` is given in run-once mode,
  where they have no effect.
- Duplicate scenario names and extract variable names starting with `env.` are
  rejected when the config is loaded.
- PyPI metadata: keywords, classifiers, and project URLs.

### Changed

- The daemon is now event-driven per scenario instead of running every scenario
  in lockstep. Configuration changes are picked up within about a second.
- An invalid configuration file is parsed once per change and its error is
  printed once, instead of on every cycle.
- Configuration validation errors show the field location and message without
  echoing the offending input, so resolved secrets cannot leak.
- Rich markup in scenario names, step names, and error text is escaped.
- `uvloop` is installed only where it is available (not on Windows), and Proofrun
  falls back to the standard `asyncio` loop. `orjson`, which was never used, is no
  longer a dependency. The minimum `pydantic` is now 2.7.
- The source is organized into packages by concern (`cli`, `config`, `runner`,
  `monitor`, `notify`, `metrics`, plus `health`) instead of a single `core` package.
  Only files moved; behavior is unchanged.
- Integration scenarios and the CI and release pipelines run against the local demo
  API (`make integration`), with no dependency on a third-party host.

### Fixed

- A failed webhook delivery printed the full webhook URL, which often contains a secret
  token, and a timeout printed nothing useful. Failures now report only the reason (an
  HTTP status, a timeout, or a connection error) and the scenario name.
- The daemon kept running with no valid configuration, looking alive while monitoring
  nothing. An invalid configuration at startup now exits with code 1. An invalid edit
  while running still keeps the last working configuration.
- The daemon was killed abruptly by `SIGTERM`, and as PID 1 in a container it never
  received the signal, so `docker stop` waited and then killed it. `SIGTERM` now stops
  it cleanly.
- `expect.status` accepted an empty list and codes outside 100 to 599, which can never
  match a response. Both are now configuration errors.
- `--interval` and `--metrics-host` were silently ignored in run-once mode. They now
  produce the same warning as `--webhook-url` and `--metrics-port`.
- A configuration with no scenarios, or a scenario with no steps, used to pass and report
  success without making a request. Both are now configuration errors.
- Misspelled field names were silently ignored, so the check they were meant to
  configure never ran. Unknown fields are now rejected with their location.
- Header mismatch errors no longer print the values of sensitive headers (names
  containing auth, cookie, token, secret, key, password, or session), so they cannot
  reach the console or webhook alerts.
- Dictionary keys that interpolate to the same name now fail the step instead of
  silently dropping one of them.
- Scenarios that ran at the same time shared one HTTP client, so a run could clear
  or read another run's cookies. Every run now has its own client.
- Removed stale `proof` naming (badges, example headers and query values, a hard-coded
  User-Agent version, and the fallback package version).

### Breaking changes

- **A daemon with an invalid configuration at startup now exits with code 1** instead of
  waiting for the file to be fixed. Under systemd or Docker, a restart policy will keep
  retrying until the file is valid.
- **Configuration validation is strict.** A file with a misspelled or unknown field, no
  scenarios, or a scenario without steps now fails to load. Run `proofrun --validate`
  on your files before upgrading.
- **The webhook environment variable is `PROOFRUN_WEBHOOK_URL`.** `PROOF_WEBHOOK_URL`
  is no longer read, and there is no alias. If you set the old name, alerts stop
  until you rename it.
- **`interval_seconds` is now per scenario.** Before, all scenarios ran together on
  the smallest interval in the file. Scenarios with different intervals now run at
  different rates. `--interval N` still runs everything every N seconds.
- Configuration validation error text has a new format.
- `${env.NAME}` is resolved at load time, so a config that contained that literal text
  needs the variable to exist (it would previously have failed at run time).
- Python imports changed. `proofrun.core` no longer exists; for example
  `proofrun.core.daemon.Daemon` is now `proofrun.monitor.daemon.Daemon`, and
  `proofrun.cli.execute_config` is replaced by `run_once` in `proofrun.cli.commands`.
  The command line is the supported interface; there is no stable Python API yet.

## [0.1.1]

Initial public release: YAML scenarios, multi-step requests with JSONPath
extraction, status, latency, header, and JSON Schema assertions, run-once and
daemon modes, webhook alerts on health changes, and hot configuration reload.
