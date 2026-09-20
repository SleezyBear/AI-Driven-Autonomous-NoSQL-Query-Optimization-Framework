FROM --platform=linux/amd64 python:3.12-slim AS wheels

WORKDIR /build
COPY requirements.txt ./
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.production.in ./
COPY --from=wheels /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.production.in \
    && rm -rf /wheels \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --chown=app:app backend/app /app/app

USER 10001:10001
CMD ["python", "-m", "app.worker.service"]
