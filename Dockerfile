# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.12.15-alpine@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d AS build

COPY --from=uv /uv /uvx /bin/

RUN apk upgrade --no-cache

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy

WORKDIR /src

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.12.15-alpine@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d

COPY --from=build /opt/venv /opt/venv

RUN python -m pip uninstall -y pip \
    && apk upgrade --no-cache \
    && adduser -S -D -H -u 10001 -s /bin/false proofrun

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER proofrun
WORKDIR /monitors

ENTRYPOINT ["proofrun"]
CMD ["--help"]
