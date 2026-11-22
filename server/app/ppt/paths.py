"""deck 路径校验、页数统计。

设计要点：渲染路径**不加载 python-pptx**。165MB 的 deck 用 python-pptx 打开
峰值约 264MB，而渲染本身还要 2GB；数页只需要读 ``ppt/presentation.xml``。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from server.app.config import settings
from server.app.ppt.errors import PptError

PRESENTATION_PART = "ppt/presentation.xml"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_pptx_archive(path: Path) -> bool:
    try:
        with ZipFile(path) as archive:
            return PRESENTATION_PART in archive.namelist()
    except (BadZipFile, OSError):
        return False


def resolve_deck(raw: str) -> Path:
    """把用户给的路径变成可信的 deck 路径。

    规则：必须是已存在的普通文件、``.pptx``、且 ``resolve()`` 后落在 ``PPT_ROOTS``
    之内。``resolve()`` 会展开符号链接，所以链接逃逸也挡得住。
    """
    if not raw or not str(raw).strip():
        raise PptError("invalid_path", "deck 路径为空")

    candidate = Path(str(raw)).expanduser()
    try:
        deck = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PptError("deck_not_found", f"文件不存在：{raw}") from exc
    except OSError as exc:
        raise PptError("invalid_path", f"路径不可用：{raw}（{exc}）") from exc

    if not deck.is_file():
        raise PptError("invalid_path", f"不是普通文件：{raw}")
    if deck.suffix.lower() != ".pptx":
        raise PptError("not_pptx", f"只支持 .pptx 文件：{deck.name}")

    roots = settings.ppt_root_paths
    if not roots:
        raise PptError("path_not_allowed", "未配置 PPT_ROOTS，拒绝访问任何路径")
    if not any(deck.is_relative_to(root) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise PptError("path_not_allowed", f"路径不在允许目录内：{allowed}")

    if not _is_pptx_archive(deck):
        raise PptError("not_pptx", f"不是有效的 pptx（缺少 {PRESENTATION_PART}）：{deck.name}")

    return deck


def slide_count(deck: Path) -> int:
    """页数：优先用 zip 里的 sldIdLst，失败再回退 python-pptx。"""
    count = _count_from_xml(deck)
    if count is not None:
        return count
    return _count_from_pptx(deck)


def _count_from_xml(deck: Path) -> int | None:
    try:
        with ZipFile(deck) as archive:
            data = archive.read(PRESENTATION_PART)
    except (KeyError, BadZipFile, OSError):
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    for node in root.iter():
        if _local_name(node.tag) == "sldIdLst":
            return sum(1 for child in node if _local_name(child.tag) == "sldId")
    return None


def _count_from_pptx(deck: Path) -> int:
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确错误
        raise PptError("unavailable", "python-pptx 未安装，无法解析 deck") from exc
    return len(Presentation(str(deck)).slides)


def validate_page(page: int, total: int) -> int:
    """页码 1-based；越界时把总页数一并返回，不静默修正。"""
    if not isinstance(page, int) or isinstance(page, bool):
        raise PptError("invalid_page", f"页码必须是整数：{page!r}")
    if page < 1 or page > total:
        raise PptError(
            "slide_out_of_range",
            f"第 {page} 页不存在，该 deck 共 {total} 页",
            page=page,
            slide_count=total,
        )
    return page
