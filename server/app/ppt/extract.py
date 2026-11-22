"""用 python-pptx 提取单页内容（文本 / 表格 / 备注 / 媒体计数）。

只在 ``ppt_get_slide`` / ``ppt_outline`` 里用；渲染路径不碰 python-pptx。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.app.ppt.errors import PptError
from server.app.ppt.paths import validate_page

MAX_TEXT_CHARS = 6000
MAX_OUTLINE_LINE_CHARS = 120
MAX_TABLE_ROWS = 30
MAX_TABLE_COLS = 12
MAX_TABLE_CELL_CHARS = 120


def _load(deck: Path):
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确错误
        raise PptError("unavailable", "python-pptx 未安装，无法解析 deck") from exc
    return Presentation(str(deck))


def _shape_lines(shape: Any) -> list[str]:
    if not getattr(shape, "has_text_frame", False):
        return []
    lines: list[str] = []
    for paragraph in shape.text_frame.paragraphs:
        text = "".join(run.text for run in paragraph.runs).strip()
        if text:
            lines.append(text)
    return lines


def _shape_type(shape: Any) -> Any:
    try:
        return shape.shape_type
    except Exception:  # noqa: BLE001 - python-pptx 对异常形状会抛 TypeError
        return None


def _table_payload(table: Any) -> dict[str, Any]:
    rows: list[list[str]] = []
    for row in list(table.rows)[:MAX_TABLE_ROWS]:
        rows.append(
            [
                (cell.text or "").strip()[:MAX_TABLE_CELL_CHARS]
                for cell in list(row.cells)[:MAX_TABLE_COLS]
            ]
        )
    return {
        "rows": len(table.rows),
        "cols": len(table.columns),
        "data": rows,
    }


def _title(slide: Any) -> str | None:
    title = slide.shapes.title
    if title is None:
        return None
    text = (title.text or "").strip()
    return text or None


def read_slide(deck: Path, page: int) -> dict[str, Any]:
    """读取第 page 页（1-based）的结构化内容。"""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = _load(deck)
    total = len(presentation.slides)
    validate_page(page, total)
    slide = presentation.slides[page - 1]

    title = _title(slide)
    text: list[str] = []
    tables: list[dict[str, Any]] = []
    image_count = 0
    has_video = False

    for shape in slide.shapes:
        text.extend(_shape_lines(shape))
        if getattr(shape, "has_table", False) and shape.has_table:
            tables.append(_table_payload(shape.table))
        shape_type = _shape_type(shape)
        if shape_type == MSO_SHAPE_TYPE.PICTURE:
            image_count += 1
        elif shape_type == MSO_SHAPE_TYPE.MEDIA:
            has_video = True

    notes = ""
    if slide.has_notes_slide:
        notes = (slide.notes_slide.notes_text_frame.text or "").strip()[:MAX_TEXT_CHARS]

    joined = "\n".join(text)
    truncated = len(joined) > MAX_TEXT_CHARS

    return {
        "page": page,
        "slide_count": total,
        "layout": slide.slide_layout.name,
        "title": title,
        "text": text,
        "text_truncated": truncated,
        "tables": tables,
        "notes": notes,
        "image_count": image_count,
        "has_video": has_video,
        "content_length": len(joined),
    }


def read_outline(deck: Path, max_slides: int) -> list[dict[str, Any]]:
    """每页标题 + 首行正文，用于整份结构解读。"""
    presentation = _load(deck)
    outline: list[dict[str, Any]] = []
    for index, slide in enumerate(presentation.slides, start=1):
        if len(outline) >= max_slides:
            break
        title = _title(slide)
        first_line = ""
        for shape in slide.shapes:
            lines = _shape_lines(shape)
            if lines and lines[0] != title:
                first_line = lines[0][:MAX_OUTLINE_LINE_CHARS]
                break
        outline.append({"page": index, "title": title, "first_line": first_line})
    return outline
