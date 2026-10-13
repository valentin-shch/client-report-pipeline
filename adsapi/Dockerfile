# Build from the repo root, it needs data/generate.py:
#   docker build -f adsapi/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
COPY adsapi/requirements.txt adsapi/requirements.txt
RUN pip install --no-cache-dir -r adsapi/requirements.txt

COPY data/generate.py data/generate.py
COPY adsapi/ adsapi/
# Generate once here rather than on every cold start (see adsapi/data.py).
RUN python -m adsapi.data /app/dataset.pkl
ENV ADSAPI_DATASET=/app/dataset.pkl

RUN useradd --create-home api
USER api

ENV PORT=8000
EXPOSE 8000
# Shell form so Render's $PORT expands. Proxy headers so the rate limit sees
# the caller's IP rather than the load balancer's.
CMD uvicorn adsapi.app:create_app_from_env --factory --host 0.0.0.0 --port $PORT \
    --proxy-headers --forwarded-allow-ips="*"
