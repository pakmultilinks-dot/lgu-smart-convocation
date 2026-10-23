# Production-oriented WSGI image; never bake a database or credentials.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/lgu/app
COPY app/requirements.txt app/requirements-server.txt ./
RUN python -m pip install --no-cache-dir -r requirements-server.txt

# .dockerignore excludes every runtime database, upload and secret.
COPY app/ ./
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin lgu
USER 10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c 'import json,urllib.request; x=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health",timeout=3)); assert x.get("ok") is True' || exit 1

# One worker is deliberate for the existing single-writer SQLite deployment.
# HTTPS/TLS termination is provided by an operator-controlled reverse proxy.
# Importing run:app enforces the schema guard BEFORE any service requests.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
