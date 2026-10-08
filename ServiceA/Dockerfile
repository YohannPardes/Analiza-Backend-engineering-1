FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/*.py .
COPY ServiceA/*.py .

ENTRYPOINT ["uvicorn", "server:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8080"]