# Dockerfile for the TeachingBench dashboard backend on Hugging Face Spaces (Docker SDK).
# HF Spaces expects port 7860 by default. Build context should be the REPO ROOT
# (so we can COPY environments/teachingbench/ alongside dashboard/backend/).
#
# Build locally:   docker build -f dashboard/backend/Dockerfile -t teachingbench-dashboard .
# Run locally:     docker run --rm -p 7860:7860 -e OPENAI_API_KEY=$OPENAI_API_KEY teachingbench-dashboard
#
# On HF Spaces, set this Dockerfile as the Space's build target. Set OPENAI_API_KEY
# as a Space secret; optionally ALLOWED_ORIGINS to your frontend's Cloudflare URL.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Backend deps first (better layer caching).
COPY dashboard/backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Then the env package (installed editable so saved tasks/* are accessible).
COPY environments/teachingbench /app/teachingbench-env
RUN pip install -e /app/teachingbench-env

# Then the FastAPI app.
COPY dashboard/backend/app.py /app/app.py

# Make a writable runs dir on HF persistent storage. Override at deploy time
# via the TEACHINGBENCH_RUNS_DIR env var if you want a different mount point.
RUN mkdir -p /data/runs
ENV TEACHINGBENCH_RUNS_DIR=/data/runs

EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
