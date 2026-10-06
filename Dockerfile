FROM python:3.12-slim

WORKDIR /app

# Only what the service needs. `COPY . /app` would ship artifacts, the local
# .env and its platform tokens into the image.
COPY pyproject.toml ./
COPY opensourceguard ./opensourceguard
COPY web ./web
COPY examples ./examples

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# A public demo that can write to GitHub is a liability, and the offline
# heuristic mode keeps the whole flow working without any token.
ENV OSG_GITHUB_TOKEN="" \
    OSG_GITEE_TOKEN="" \
    OSG_GITLAB_TOKEN="" \
    OSG_MODELSCOPE_TOKEN=""

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4).status==200 else 1)"

# --host 0.0.0.0 is required inside a container; the CLI default stays loopback.
CMD ["python", "-m", "opensourceguard.cli", "serve", "--repo", "/app/examples/buggy_csv", "--port", "8787", "--host", "0.0.0.0"]
