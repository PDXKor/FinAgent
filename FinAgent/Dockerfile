FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# Choose the LLM extra at build time: --build-arg LLM_EXTRA=anthropic|openai|ollama
ARG LLM_EXTRA=ollama
RUN pip install --no-cache-dir ".[${LLM_EXTRA}]"
VOLUME /app/reports
# `serve` runs the built-in scheduler; override with `run` for CronJob-style one-shot execution.
ENTRYPOINT ["finagent"]
CMD ["serve"]
