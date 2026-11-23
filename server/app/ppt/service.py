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
MAX_PAGES_PER_CALL = 32


def parse_pages(spec: str) -> list[int]:
    """解析 "5" / "5,6,9" / "5-8" / "5-8,12" 这类页码写法。"""
    if not isinstance(spec, str) or not spec.strip():
        raise PptError("invalid_page", "pages 不能为空，例如 '5' 或 '5-8' 或 '5,6,9'")

    pages: list[int] = []
    for chunk in spec.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError as exc:
                raise PptError("invalid_page", f"无法解析页码区间：{chunk}") from exc
            if start > end:
                start, end = end, start
            pages.extend(range(start, end + 1))
        else:
            try:
                pages.append(int(chunk))
            except ValueError as exc:
                raise PptError("invalid_page", f"无法解析页码：{chunk}") from exc

    if not pages:
        raise PptError("invalid_page", "没有解析出任何页码")
    if len(pages) > MAX_PAGES_PER_CALL:
        raise PptError(
            "too_many_pages",
            f"一次最多渲染 {MAX_PAGES_PER_CALL} 页（收到 {len(pages)} 页），请分批请求",
        )
    return pages


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


def _group_pages(pages: list[int], max_batch: int) -> list[list[int]]:
    """把页码分组：连续页合成一组，每组不超过 ``max_batch``。

    一次请求里的连续页合并渲染只付一次 soffice 启动成本（约 0.45s），但组越大
    内存越高（1 页 236MB / 8 页 318MB / 32 页 528MB），所以按上限切。
    """
    groups: list[list[int]] = []
    current: list[int] = []
    for page in pages:
        if current and (page != current[-1] + 1 or len(current) >= max_batch):
            groups.append(current)
            current = []
        current.append(page)
    if current:
        groups.append(current)
    return groups


def render_slide(
    page: int, path: str | None = None, dpi: int | None = None
) -> dict[str, Any]:
    """渲染单页（``ppt_render_slide`` 的入口）。"""
    return render_pages([page], path, dpi)[0]


def render_pages(
    pages: list[int], path: str | None = None, dpi: int | None = None
) -> list[dict[str, Any]]:
    """渲染一页或多页；返回值与 ``pages`` 同序，重复页只渲染一次。"""
    if not isinstance(pages, list) or not pages:
        raise PptError("invalid_page", "pages 不能为空")

    deck = _deck_or_path(path)
    total = slide_count(deck)
    for page in pages:
        validate_page(page, total)
    resolved_dpi = _resolve_dpi(dpi)

    if not render.tools_available():
        raise PptError(
            "render_unavailable",
            "容器内缺少 soffice 或 pdftoppm，无法渲染（请使用带 LibreOffice 的镜像）",
        )

    ordered: list[int] = []
    for page in pages:
        if page not in ordered:
            ordered.append(page)

    results: dict[int, dict[str, Any]] = {}
    missing: list[int] = []
    for page in ordered:
        cached = render.png_path(deck, page, resolved_dpi)
        if cached.is_file() and cached.stat().st_size > 0:
            width, height = render.png_size(cached)
            results[page] = {
                "path": str(cached),
                "page": page,
                "slide_count": total,
                "dpi": resolved_dpi,
                "width": width,
                "height": height,
                "cached": True,
                "ms": 0,
            }
        else:
            missing.append(page)

    if missing:
        # LO 单页峰值已降到约 240MB，但仍是重进程；不并发，等不到就明确报错
        if not _RENDER_LOCK.acquire(timeout=settings.ppt_timeout):
            raise PptError("render_timeout", "已有渲染任务在运行，请稍后重试")
        try:
            for group in _group_pages(sorted(missing), settings.ppt_batch_max):
                for item in render.render_pages_png(deck, group, resolved_dpi, total):
                    results[item["page"]] = item
        finally:
            _RENDER_LOCK.release()

    return [results[page] for page in pages]
