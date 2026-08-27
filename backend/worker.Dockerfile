FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY backend/app /app/app

CMD ["python", "-m", "app.worker.service"]
