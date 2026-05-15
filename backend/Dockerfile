FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Install dependencies first for Docker layer caching
COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY . .

# CMD is overridden by docker-compose.yml command:
# bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
