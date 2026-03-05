# ── Stage 1: dependencies ──────────────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN mkdir -p crazyjob && touch crazyjob/__init__.py
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[flask]"


# ── Stage 2: development ───────────────────────────────────────────────────────
FROM deps AS development

RUN pip install --no-cache-dir ".[dev]"

COPY . .

RUN useradd --create-home appuser
USER appuser

CMD ["flask", "run", "--host=0.0.0.0"]


# ── Stage 3: production ────────────────────────────────────────────────────────
FROM deps AS production

COPY crazyjob/ ./crazyjob/
COPY pyproject.toml .

RUN useradd --create-home appuser
USER appuser

CMD ["crazyjob", "worker", "--all-queues", "--concurrency", "10"]
