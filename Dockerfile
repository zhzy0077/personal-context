# Use Python 3.13 slim image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies (if needed in the future)
# RUN apt-get update && apt-get install -y \
#     && rm -rf /var/lib/apt/lists/*

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
COPY main.py ./

# Install Python dependencies
RUN uv sync --frozen

# Create data directory for SQLite database
RUN mkdir -p /data

# Set environment variable for database path
ENV PERSONAL_CONTEXT_DB_PATH=/data/context.db

# Set HTTP server to listen on all interfaces
ENV PERSONAL_CONTEXT_HTTP_HOST=0.0.0.0
ENV PERSONAL_CONTEXT_HTTP_PORT=8000

# Expose HTTP server port
EXPOSE 8000

# Run the HTTP server by default
CMD ["uv", "run", "main.py"]
