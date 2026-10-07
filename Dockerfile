# syntax=docker/dockerfile:1

FROM python:3.12.15-alpine AS build

RUN apk upgrade --no-cache

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install .

FROM python:3.12.15-alpine

COPY --from=build /opt/venv /opt/venv

RUN apk upgrade --no-cache \
    && adduser -S -D -H -u 10001 -s /bin/false proofrun

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER proofrun
WORKDIR /monitors

ENTRYPOINT ["proofrun"]
CMD ["--help"]
