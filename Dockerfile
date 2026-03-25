FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv sync --no-dev
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "autodialectics.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
