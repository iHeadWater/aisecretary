"""PPT 业务编排：路径/页码校验、单并发渲染、当前 deck 状态。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.app.config import settings
from server.app.database import get_connection, init_db
from server.app.ppt import extract, render
from server.app.ppt.errors import PptError
from server.app.ppt.paths import resolve_deck, slide_count, validate_page

_RENDER_LOCK = threading.Lock()
_STATE_KEY = "current_deck"
DPI_MIN = 72
DPI_MAX = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_deck(deck: Path) -> None:
    init_db()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO ppt_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (_STATE_KEY, str(deck), _utc_now()),
        )


def _load_deck_path() -> str | None:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM ppt_state WHERE key = ?", (_STATE_KEY,)
        ).fetchone()
    return row["value"] if row else None


def _clear_deck() -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM ppt_state WHERE key = ?", (_STATE_KEY,))


def _deck_payload(deck: Path, count: int) -> dict[str, Any]:
    stat = deck.stat()
    return {
        "path": str(deck),
        "file_name": deck.name,
        "slide_count": count,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _current_deck() -> Path:
    raw = _load_deck_path()
    if not raw:
        raise PptError(
            "no_deck", "还没有设置当前 deck：先调用 ppt_use_deck，或在参数里传 path"
        )
    try:
        return resolve_deck(raw)
    except PptError as exc:
        _clear_deck()
        raise PptError(
            "no_deck", f"上次记录的 deck 已不可用（{exc.message}）：{raw}"
        ) from exc


def _deck_or_path(path: str | None) -> Path:
    if path and str(path).strip():
        return resolve_deck(path)
    return _current_deck()


def _resolve_dpi(dpi: int | None) -> int:
    value = settings.ppt_dpi if dpi is None else dpi
    if not isinstance(value, int) or isinstance(value, bool):
        raise PptError("invalid_dpi", f"dpi 必须是整数：{value!r}")
    if not DPI_MIN <= value <= DPI_MAX:
        raise PptError(
            "invalid_dpi", f"dpi 需在 {DPI_MIN}-{DPI_MAX} 之间：{value}", dpi=value
        )
    return value


def use_deck(path: str) -> dict[str, Any]:
    deck = resolve_deck(path)
    count = slide_count(deck)
    _save_deck(deck)
    return _deck_payload(deck, count)


def get_deck() -> dict[str, Any]:
    deck = _current_deck()
    return _deck_payload(deck, slide_count(deck))


def outline(path: str | None = None, max_slides: int | None = None) -> list[dict[str, Any]]:
    deck = _deck_or_path(path)
    total = slide_count(deck)
    limit = settings.ppt_max_slides_outline if max_slides is None else max_slides
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        limit = 1
    limit = min(limit, settings.ppt_max_slides_outline, total)
    return extract.read_outline(deck, limit)


def get_slide(page: int, path: str | None = None) -> dict[str, Any]:
    deck = _deck_or_path(path)
    total = slide_count(deck)
    validate_page(page, total)
    payload = extract.read_slide(deck, page)
    payload["path"] = str(deck)
    return payload


def render_slide(
    page: int, path: str | None = None, dpi: int | None = None
) -> dict[str, Any]:
    deck = _deck_or_path(path)
    total = slide_count(deck)
    validate_page(page, total)
    resolved_dpi = _resolve_dpi(dpi)

    if not render.tools_available():
        raise PptError(
            "render_unavailable",
            "容器内缺少 soffice 或 pdftoppm，无法渲染（请使用带 LibreOffice 的镜像）",
        )

    # LO 单页峰值约 2GB，不能并发；等不到锁就直接报超时，不排队堆积
    if not _RENDER_LOCK.acquire(timeout=settings.ppt_timeout):
        raise PptError("render_timeout", "已有渲染任务在运行，请稍后重试")

    try:
        return render.render_slide_png(deck, page, resolved_dpi, total)
    finally:
        _RENDER_LOCK.release()
