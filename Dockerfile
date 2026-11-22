# ---------- builder：装依赖 + 用 git tag 推导版本号 ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

# hatch-vcs 调用 git describe 取版本，builder 里必须有 git 可执行文件
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# 先只装依赖，源码变动时可以复用这一层
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# .git 一并进构建上下文（约 2MB）：hatch-vcs 靠 git tag 推导版本号。
# 没有 .git 时（例如从 tarball 构建）回退到 pyproject 的 fallback-version。
COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------- runtime：只要 venv，不带 git / uv / 源码仓库 ----------
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY skills/ ./skills/
COPY prompts/ ./prompts/

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH=/data/transactions.sqlite

EXPOSE 8000

CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
