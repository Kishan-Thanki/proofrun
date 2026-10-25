PYTHON ?= python3

.PHONY: install test coverage coverage-html lint format format-check typecheck check \
	serve integration build dist-smoke clean full

full: clean install check build

install:
	uv sync --group dev

test:
	uv run pytest -q

coverage:
	uv run pytest -q --cov=proofrun --cov-branch \
		--cov-report=term-missing \
		--cov-fail-under=100

coverage-html:
	uv run pytest -q --cov=proofrun --cov-branch \
		--cov-report=html
	@echo "Coverage report generated: htmlcov/index.html"

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format --check src/ tests/
	uv run ruff check src/ tests/

typecheck:
	uv run pyright

audit:
	uv run pip-audit

check: lint format-check typecheck audit coverage

serve:
	$(PYTHON) scenarios/server.py

integration:
	@$(PYTHON) scenarios/server.py & \
	SERVER_PID=$$!; \
	trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
	up=0; \
	for i in $$(seq 1 50); do \
		$(PYTHON) -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8099/health')" \
			>/dev/null 2>&1 && up=1 && break; \
		sleep 0.2; \
	done; \
	if [ $$up -ne 1 ]; then \
		echo "The demo API did not start on 127.0.0.1:8099. Is '$(PYTHON)' installed and the port free?"; \
		echo "Try: make integration PYTHON=/path/to/python3"; \
		exit 1; \
	fi; \
	export DEMO_PASSWORD=demo-password; \
	status=0; \
	for name in profile auth chain crud resilient; do \
		echo "==> scenarios/$$name.yaml"; \
		uv run proofrun scenarios/$$name.yaml --validate >/dev/null || status=1; \
		uv run proofrun scenarios/$$name.yaml || status=1; \
	done; \
	exit $$status

dist-smoke:
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	for pkg in dist/*.whl dist/*.tar.gz; do \
		echo "==> installing $$pkg in a clean environment"; \
		$(PYTHON) -m venv "$$tmp/venv"; \
		"$$tmp/venv/bin/pip" install --quiet "$$pkg"; \
		"$$tmp/venv/bin/proofrun" --version; \
		DEMO_PASSWORD=smoke "$$tmp/venv/bin/proofrun" scenarios/resilient.yaml --validate >/dev/null; \
		rm -rf "$$tmp/venv"; \
	done

build:
	uv build

clean:
	rm -rf dist/ \
		.ruff_cache/ \
		.pytest_cache/ \
		.pyright_cache/ \
		.coverage \
		.coverage.* \
		htmlcov/ \
		__pycache__/ \
		*.egg-info/
