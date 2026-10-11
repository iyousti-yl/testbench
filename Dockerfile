FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TESTBENCH_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]" \
    && useradd --create-home --uid 10001 testbench \
    && mkdir -p /data && chown testbench /data

USER testbench
EXPOSE 8000

# Seeds the synthetic demo on first start, then serves the app.
CMD ["sh", "-c", "testbench web seed-demo --if-empty && exec testbench web serve --host 0.0.0.0"]
