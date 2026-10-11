FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TESTBENCH_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web,datasphere]" \
    && useradd --create-home --uid 10001 testbench \
    && mkdir -p /data && chown testbench /data

USER testbench
EXPOSE 8000

# Creates the first account from TESTBENCH_ADMIN_EMAIL / _PASSWORD when set, then serves.
CMD ["sh", "-c", "if [ -n \"$TESTBENCH_ADMIN_EMAIL\" ]; then TESTBENCH_NEW_PASSWORD=\"$TESTBENCH_ADMIN_PASSWORD\" testbench web create-user \"$TESTBENCH_ADMIN_EMAIL\" --name Admin --if-missing || exit 1; fi; exec testbench web serve --host 0.0.0.0"]
