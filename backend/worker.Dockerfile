FROM --platform=linux/amd64 python:3.10-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

CMD ["python", "-c", "import time; time.sleep(2147483647)"]

