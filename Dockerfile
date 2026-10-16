FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ruff/bandit/radon are pinned in requirements.txt and installed with everything
# else: the analysis engine records the analyzer versions it executed, so they
# must not be installed a second time unpinned.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render injects PORT (10000 by default); local runs fall back to 8000.
# Migrations run before every start so a fresh database gets its schema.
# `exec` makes uvicorn PID 1 so SIGTERM from Render reaches it.
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
