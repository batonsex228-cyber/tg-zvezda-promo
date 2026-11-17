# Zvezdochka Telegram v1.0.4 - long polling, no inbound HTTP port required.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 zvezdochka \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app zvezdochka \
    && mkdir -p /app/runtime \
    && chown -R 10001:10001 /app

COPY --chown=10001:10001 app/ ./app/
COPY --chown=10001:10001 data/ ./data/
COPY --chown=10001:10001 assets/ ./assets/

# Only runtime/ is persistent; never bake the token, .env, or live SQLite into an image.
VOLUME ["/app/runtime"]
USER 10001:10001
STOPSIGNAL SIGTERM
CMD ["python", "-m", "app.main"]
