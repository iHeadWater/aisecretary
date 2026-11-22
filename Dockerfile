FROM python:3.12-slim

# uv 负责依赖安装与打包，和本地开发用同一套工具
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# 先只装依赖，源码变动时可以复用这一层
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# .git 一并进镜像（约 2MB）：hatch-vcs 靠 git tag 推导版本号。
# 没有 .git 时（例如从 tarball 构建）回退到 pyproject 的 fallback-version。
COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Default database path inside container — override via DATABASE_PATH env var
ENV DATABASE_PATH=/data/transactions.sqlite

EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
