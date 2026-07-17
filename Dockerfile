FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini main.py ./
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# api is the default; docker-compose.yml overrides `command:` for worker
# to `python -m app.worker_main` — same image, same code, different entrypoint.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
