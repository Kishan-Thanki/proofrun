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

An endpoint can return `200 OK` while its payload is missing a critical field. And even when individual endpoints respond, an API journey breaks when one step depends on data returned by another.

<div align="center">
  <img src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/assets/proofrun-thumbnail.svg" alt="Proofrun reporting a passing scenario" width="860">
</div>

**Proofrun validates individual API responses and multi-step workflows** using clean, readable YAML scenarios.

- Check status codes, latency thresholds, headers, and JSON Schema contracts.
- Extract response values and pass them dynamically into subsequent steps.
- Run the exact same scenarios on your laptop, inside CI pipelines, or as a background daemon.
- No external services required: no PostgreSQL, Redis, or external cloud accounts required.

<div align="center">
  <img
    src="https://raw.githubusercontent.com/Kishan-Thanki/proofrun/main/docs/assets/demo-fail.svg"
    alt="Proofrun reporting a failed step in a multi-step scenario"
    width="860"
  >
</div>

---

## Quickstart (30 seconds)

### 1. Install
```bash
pip install proofrun
```

### 2. Define a Scenario (`monitors.yaml`)
```yaml
version: "1.0"

global:
  base_url: "https://jsonplaceholder.typicode.com"

scenarios:
  - name: "Post API Contract"
    steps:
      - name: "Fetch post"
        request:
          method: GET
          path: /posts/1
        expect:
          status: 200
          max_latency_ms: 800
          schema:
            type: object
            required: [id, title, userId]
```

### 3. Run It
```bash
proofrun monitors.yaml
```

---

## Multi-Step Workflows

A workflow connects dependent requests: authenticate, extract an ID or token, and use it downstream.

```yaml
version: "1.0"

global:
  base_url: "https://api.example.com"
  timeout_seconds: 5

scenarios:
  - name: "Public Posts Journey"
    steps:
      - name: "Create post"
        request:
          method: POST
          path: /posts
          json:
            title: "Test Title"
            body: "Content"
            userId: 1
        expect:
          status: 201
        extract:
          post_id: "$.id"

      - name: "Fetch created post"
        request:
          method: GET
          path: "/posts/${post_id}"
        expect:
          status: 200
          schema:
            type: object
            required: [id]
```

Proofrun executes steps sequentially and stops at the first failure, clearly reporting where the journey broke.

---

## Environment Variables & Secrets

Supply credentials securely using `${env.NAME}`:

```yaml
version: "1.0"

global:
  base_url: "https://api.example.com"
  headers:
    Authorization: "Bearer ${env.API_TOKEN}"

scenarios:
  - name: "Authenticated Account Check"
    steps:
      - name: "Get profile"
        request:
          method: GET
          path: /profile
        expect:
          status: 200
```

---

## Continuous Daemon & Alerting

Run Proofrun as a continuous synthetic monitor with transition-based alerting and observability metrics:

```bash
# Run continuously as a background daemon
proofrun monitors.yaml --daemon --interval 60 --webhook-url https://hooks.example.com/alerts
```

- **Transition-based alerts**: Alerts only fire when a scenario status transitions (`HEALTHY -> FAILING` or recovers back to `HEALTHY`), eliminating alert fatigue.
- **Hot reload**: Edits to scenario YAML are picked up live without downtime.
- **Built-in observability**: Serve metrics in standard text exposition format:
  ```bash
  proofrun monitors.yaml --daemon --metrics-port 9464
  curl http://127.0.0.1:9464/metrics
  ```

---

## CI / CD Integration

Use Proofrun in GitHub Actions or any CI system. It exits `0` on success and `1` on failure:

```yaml
- name: Validate scenario configuration
  run: proofrun monitors.yaml --validate

- name: Run synthetic tests
  run: proofrun monitors.yaml
  env:
    API_TOKEN: ${{ secrets.API_TOKEN }}
```

---

## Docker

Official container images are published to GitHub Container Registry:

```bash
# Run one-off test
docker run --rm \
  -v "$PWD/monitors.yaml:/monitors.yaml:ro" \
  -e API_TOKEN \
  ghcr.io/kishan-thanki/proofrun /monitors.yaml

# Run as a continuous daemon with host loopback metrics
docker run -d --name proofrun --restart unless-stopped \
  -v "$PWD/monitors.yaml:/monitors.yaml:ro" \
  -e API_TOKEN \
  -e PROOFRUN_METRICS_PORT=9464 \
  -e PROOFRUN_METRICS_HOST=0.0.0.0 \
  -p 127.0.0.1:9464:9464 \
  ghcr.io/kishan-thanki/proofrun /monitors.yaml --daemon --allow-remote-metrics
```

---

## CLI Overview

```bash
proofrun <config.yaml>                 # Run once (default)
proofrun <config.yaml> --once          # Run once explicitly
proofrun <config.yaml> --validate      # Validate YAML syntax and schemas without sending requests
proofrun <config.yaml> --daemon        # Run continuously as a monitoring daemon
proofrun <config.yaml> --daemon -i 30  # Override scenario intervals (30s)
proofrun <config.yaml> --daemon --webhook-url <url>
proofrun <config.yaml> --daemon --metrics-port 9464
proofrun <config.yaml> --daemon --metrics-port 9464 --metrics-host 0.0.0.0 --allow-remote-metrics
proofrun --version                     # Show installed version
```

---

## Documentation & Reference

For detailed technical references, see:
- [Full Configuration & Assertion Reference](docs/reference.md): Complete schema models, assertions, built-in dynamic variables (`${$uuid}`, `${$timestamp}`), retries, and thresholds.
- [Security Policy](SECURITY.md): Vulnerability disclosure, trust boundaries, and redaction details.
- [Roadmap & Growth Path](docs/roadmap.md): Project roadmap, core philosophy, and upcoming capabilities.

---

## License

[MIT](LICENSE)
