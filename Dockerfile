FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRYPTO_OPTIONS_RUNTIME_PROFILE=production

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --chown=app:app LICENSE LICENSE-DATA ./
COPY --chown=app:app crypto_options_report ./crypto_options_report

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=3)); raise SystemExit(0 if data.get('status') == 'alive' else 1)"]

CMD ["python", "-m", "crypto_options_report.api", "--runtime-profile", "production", "--host", "127.0.0.1", "--port", "8000"]
