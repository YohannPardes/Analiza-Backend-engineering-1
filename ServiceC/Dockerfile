FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx

COPY common/*.py .
COPY ServiceC/*.py .

ENTRYPOINT ["uvicorn", "server:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8080"]