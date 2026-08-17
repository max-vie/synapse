FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

WORKDIR /app

RUN groupadd --system --gid 10001 synapse \
    && useradd --system --uid 10001 --gid synapse --home-dir /home/synapse --create-home synapse

# Install the application and runtime dependencies at build time.
COPY pyproject.toml README.md LICENSE /app/
COPY VERSION /app/VERSION
COPY src /app/src
RUN python -m pip install --no-cache-dir .

RUN chown -R synapse:synapse /app /home/synapse

USER synapse

WORKDIR /app

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

CMD ["python", "-m", "synapse.service"]
