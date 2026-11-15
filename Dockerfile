# syntax=docker/dockerfile:1
# One container for the hosted demo: trade server (internal, :8000) + screens (public, $PORT).
# Runs on Hugging Face Spaces (user 1000, port 7860). See deploy/README.md.

FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" PORT=7860
RUN pip install --no-cache-dir uv==0.9.25 && useradd -m -u 1000 user && mkdir /app && chown user:user /app
USER user
WORKDIR /app
COPY --chown=user pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=user . .
COPY --chown=user --from=ui /ui/dist ./frontend/dist
# The Valio Aimo files are never committed. Railway gets data/raw/ in the local upload; a
# Space would get deploy/data.enc instead (see deploy/unpack_data.py). Then → data/catalog.db.
RUN python deploy/unpack_data.py && python -m catalog.load
EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
