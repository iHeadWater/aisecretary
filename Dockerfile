FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir mcp

# Copy application code
COPY server/ ./server/
COPY skills/ ./skills/
COPY prompts/ ./prompts/

# Default database path inside container — override via DATABASE_PATH env var
ENV DATABASE_PATH=/data/transactions.sqlite

EXPOSE 8000

CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
