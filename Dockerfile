# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install the package itself.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# HTTP (streamable) transport so MCP hosts can reach the server over the network.
# Override CMD with `--transport stdio` if you embed it as a local subprocess.
ENTRYPOINT ["chart-mcp"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
