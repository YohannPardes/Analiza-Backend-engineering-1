FROM python:3.11-slim

WORKDIR /app

COPY kafka-consumer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/*.py .
COPY kafka-consumer/*.py .

ENTRYPOINT ["python", "-u", "process.py"]
