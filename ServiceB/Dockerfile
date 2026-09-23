FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn

COPY ServiceB/*.py .

ENTRYPOINT ["uvicorn", "server:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8080"]