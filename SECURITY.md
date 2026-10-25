# Security Policy

## Reporting a vulnerability

Do not report suspected vulnerabilities in public issues. Use the private vulnerability reporting feature for this repository if enabled. Otherwise, contact the maintainer privately through the GitHub profile. Include the affected version or commit, reproduction steps, and potential impact. Do not include real credentials or production data.

## Supported versions

The latest released version and the main branch are the primary targets for security fixes. Older releases may not receive backported fixes. Upgrade to the latest release where possible.

## Trust boundary

Proofrun treats scenario YAML as operator-controlled configuration. Running a scenario sends HTTP requests to destinations specified by the configuration, including public services, private networks, loopback addresses, and internal services reachable by the Proofrun process. This is intentional; Proofrun does not enforce a default outbound-host allowlist.

Only run scenario files you trust, especially when Proofrun has access to production credentials or privileged networks. Do not run untrusted pull-request scenarios with production secrets or privileged network access.

References such as `${env.NAME}` are resolved from the process environment during configuration loading. A configuration can cause those values to be sent to the configured API. Protect environment variables and scenario files accordingly.

## Secrets and diagnostic output

Secret redaction is best-effort, not a guarantee that every secret will be removed from every output. Avoid placing credentials in scenario names or user-facing labels. Treat terminal output and webhook notifications as potentially sensitive. Arbitrary response content and runtime-extracted values are not comprehensively redacted.

## Metrics and webhooks

The metrics endpoint has no authentication and binds to loopback by default. Binding to a non-loopback address requires explicit opt-in with `--allow-remote-metrics`; this does not add authentication. Use network controls to restrict access. Configure webhooks only for trusted destinations.

## Container image verification

Release container images are intended to include SBOM and provenance attestations and to be signed by digest. Follow the Docker section of the README to verify a release signature before trusting a published image.
