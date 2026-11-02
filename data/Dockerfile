# Data API + recon jobs. State lives in the /data volume (SQLite, raw SEC responses, slice.txt).
FROM python:3.13.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN pip install -c constraints.txt . \
 && useradd --uid 1000 --create-home app \
 && mkdir /data && chown app /data
USER app

ENV FINAGENT_DB_PATH=/data/finagent.db \
    FINAGENT_RAW_DIR=/data/raw \
    FINAGENT_SLICE_FILE=/data/slice.txt \
    FINAGENT_API_HOST=0.0.0.0 \
    FINAGENT_API_PORT=8765
VOLUME /data
EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD python -c "\
import os, urllib.request as u; t = os.environ.get('FINAGENT_API_TOKEN'); \
u.urlopen(u.Request('http://127.0.0.1:8765/v1/health', \
headers={'Authorization': f'Bearer {t}'} if t else {}), timeout=2)"

CMD ["finagent-data", "serve"]
