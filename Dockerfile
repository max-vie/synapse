FROM python:3.13-slim

WORKDIR /app

# Install the application and runtime dependencies at build time.
COPY pyproject.toml README.md LICENSE /app/
COPY VERSION /app/VERSION
COPY src /app/src
RUN python -m pip install --no-cache-dir .

WORKDIR /app

EXPOSE 8080

CMD ["python", "-m", "synapse.service"]
