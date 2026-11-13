FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    TRADINGAGENTS_IN_DOCKER=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 10001 appuser \
 && install -d -m 0750 -o appuser -g appuser /home/appuser/.tradingagents

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY tradingagents tradingagents
COPY cli cli
COPY backend backend

RUN uv sync --frozen --extra dashboard --no-dev --no-install-project \
 && uv pip install --python /app/.venv/bin/python -e . --no-deps \
 && chown -R appuser:appuser /app

COPY deploy/api-entrypoint.sh /usr/local/bin/desk-api
RUN chmod 0755 /usr/local/bin/desk-api

ARG GIT_COMMIT=unknown
ENV TRADINGAGENTS_BUILD_COMMIT=${GIT_COMMIT}

USER appuser
EXPOSE 8000
ENTRYPOINT ["desk-api"]
