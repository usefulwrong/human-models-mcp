ARG PYTHON_BASE=python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
FROM ${PYTHON_BASE} AS runtime-deps
RUN apt-get update && apt-get install -y --no-install-recommends libosmesa6 libegl1 libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
FROM runtime-deps AS runtime
ARG PYTHON_BASE
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MUJOCO_GL=osmesa OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 HUMAN_MODELS_HOME=/app MPLCONFIGDIR=/tmp/matplotlib XDG_CACHE_HOME=/tmp/.cache
COPY . .
RUN pip install --no-deps --no-build-isolation . && python scripts/capture_environment.py --base-image "$PYTHON_BASE" && mkdir -p /app/results /app/reports /app/render_jobs && chown -R 1000:1000 /app/results /app/reports /app/render_jobs
USER 1000:1000
ENTRYPOINT ["python", "-m", "human_models_mcp"]
