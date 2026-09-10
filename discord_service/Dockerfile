FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY discord_service ./discord_service
ENV PATH="/app/.venv/bin:$PATH" TZ=Asia/Seoul PYTHONUNBUFFERED=1
CMD ["python", "-m", "discord_service", "run"]
