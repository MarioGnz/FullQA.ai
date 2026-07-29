FROM python:3.11-slim

# Install curl for the Docker healthcheck only
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1000 qauser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Data directory for SQLite (will be overridden by the qa-data volume)
RUN mkdir -p /app/data && chown -R qauser:qauser /app

USER qauser

WORKDIR /app/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
