FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies at build time — never pip-install on startup.
COPY requirements/runtime.txt /app/requirements/runtime.txt
RUN python -m pip install --no-cache-dir -r /app/requirements/runtime.txt

# Copy application source (mounted :ro at runtime, but also baked in for
# standalone image use).
COPY VERSION /app/VERSION
COPY scripts /app/scripts

WORKDIR /app/scripts

EXPOSE 8080

CMD ["python", "-m", "synapse.service"]