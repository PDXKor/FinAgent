# Agents API server (`serve`); the same image runs CLI commands via `docker compose run`.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --uid 1000 --create-home app
USER app

ENV FINAGENT_AGENTS_API_HOST=0.0.0.0 \
    FINAGENT_AGENTS_API_PORT=8766
EXPOSE 8766

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD python -c "\
import os, urllib.request as u; t = os.environ.get('FINAGENT_AGENTS_API_TOKEN'); \
u.urlopen(u.Request('http://127.0.0.1:8766/v1/health', \
headers={'Authorization': f'Bearer {t}'} if t else {}), timeout=2)"

ENTRYPOINT ["finagent-agents"]
CMD ["serve"]
