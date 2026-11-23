"""把 deck 裁成「只含指定几页」的临时 pptx，供 LibreOffice 渲染。

为什么需要：LibreOffice 渲染任意一页都会把整本 deck 载入内存。实测一本 158MB /
64 页的 deck，渲染单页峰值 1.3–2.0GB、耗时 9–11 秒；把目标页单独裁成 0.8MB 的
pptx 后，峰值 236MB、耗时 0.6 秒，而 PDF 内容与原 deck 逐字节等价。

裁剪规则：
- 只带 ``presentation.xml`` / ``[Content_Types].xml`` / 所有 layout、master、theme
  等结构件（它们很小，缺了会让 LO 拒绝加载）；
- 只带目标页的 ``slideN.xml`` 与它引用到的 ``ppt/media/*``；
- 丢掉 ``notesSlides`` / ``comments`` / ``tags`` 等与渲染无关的部分；
- 裁掉 ``presentation.xml`` 里的 ``sldIdLst``，只保留目标页；
- 把 ``slidenum`` 域改写成字面页码 —— 否则切片后页码会变成「1」。
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path

from server.app.ppt.errors import PptError

PRESENTATION_PART = "ppt/presentation.xml"
PRESENTATION_RELS = "ppt/_rels/presentation.xml.rels"
CONTENT_TYPES = "[Content_Types].xml"
ROOT_RELS = "_rels/.rels"

# 这些前缀/文件只属于「别的页」或与渲染无关，整体不进切片
_DROP_PREFIXES = (
    "ppt/media/",
    "ppt/notesSlides/",
    "ppt/comments/",
    "ppt/tags/",
    "ppt/changesInfos/",
    # 各页自己的 rels：目标页的会由 BFS 重新加回来，其余页的一律不进
    "ppt/slides/_rels/",
)
_DROP_FILES = {
    "ppt/commentAuthors.xml",
    "ppt/authors.xml",
    "ppt/revisionInfo.xml",
}
_SLIDE_PART_RE = re.compile(r"ppt/slides/slide\d+\.xml$")
_REL_RE = re.compile(r"<Relationship [^>]*/>")
_SLIDE_NUM_FIELD_RE = re.compile(
    r'<a:fld[^>]*type="slidenum"[^>]*>.*?</a:fld>', re.S
)
_RPR_RE = re.compile(r"<a:rPr[^>]*/>|<a:rPr[^>]*>.*?</a:rPr>", re.S)


def _rels_part(part: str) -> str:
    directory, name = posixpath.split(part)
    return posixpath.join(directory, "_rels", name + ".rels")


def _resolve_target(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def _parse_rels(xml: str, rels_part: str) -> list[tuple[str, str, bool]]:
    """返回 (原始 Relationship 片段, 目标 part, 是否外部链接)。"""
    base_dir = posixpath.dirname(posixpath.dirname(rels_part))
    items: list[tuple[str, str, bool]] = []
    for match in _REL_RE.finditer(xml):
        tag = match.group(0)
        target_match = re.search(r'Target="([^"]+)"', tag)
        if not target_match:
            continue
        external = 'TargetMode="External"' in tag
        items.append((tag, _resolve_target(base_dir, target_match.group(1)), external))
    return items


def _filter_rels(xml: str, rels_part: str, kept: set[str]) -> str:
    """丢掉指向「已不存在的 part」的关系，避免 LO 遇到悬空引用。"""
    items = _parse_rels(xml, rels_part)
    drop = [tag for tag, target, external in items if not external and target not in kept]
    for tag in drop:
        xml = xml.replace(tag, "", 1)
    return xml


def _page_map(
    archive: zipfile.ZipFile,
) -> tuple[str, dict[int, tuple[str, str]], dict[str, int]]:
    """读 presentation.xml。

    返回 ``(presentation.xml 文本, {页码: (sldId 片段, slide part)}, {slide part: 页码})``。
    """
    try:
        presentation = archive.read(PRESENTATION_PART).decode("utf-8")
        rels = archive.read(PRESENTATION_RELS).decode("utf-8")
    except KeyError as exc:  # pragma: no cover - resolve_deck 已经校验过
        raise PptError("not_pptx", "deck 缺少 presentation 部件") from exc

    rel_targets = dict(_rid_targets(rels))
    id_list = re.search(r"<p:sldIdLst>.*?</p:sldIdLst>", presentation, re.S)
    if not id_list:
        raise PptError("not_pptx", "deck 缺少 sldIdLst")

    by_page: dict[int, tuple[str, str]] = {}
    page_of: dict[str, int] = {}
    for page, entry in enumerate(re.findall(r"<p:sldId [^>]*/>", id_list.group(0)), start=1):
        rid_match = re.search(r'r:id="([^"]+)"', entry)
        if not rid_match:
            continue
        slide_rel = rel_targets.get(rid_match.group(1))
        if not slide_rel:
            continue
        slide_part = _resolve_target("ppt", slide_rel)
        by_page[page] = (entry, slide_part)
        page_of[slide_part] = page
    return presentation, by_page, page_of


def _rid_targets(rels_xml: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for tag, _target, external in _parse_rels(rels_xml, PRESENTATION_RELS):
        if external:
            continue
        rid = re.search(r'Id="([^"]+)"', tag)
        target = re.search(r'Target="([^"]+)"', tag)
        if rid and target:
            pairs.append((rid.group(1), target.group(1)))
    return pairs


def _fix_slide_number(slide_xml: str, page: int) -> str:
    """把 slidenum 域替换成字面页码，保留原有字符格式。"""

    def repl(match: re.Match[str]) -> str:
        body = match.group(0)
        rpr = _RPR_RE.search(body)
        return f"<a:r>{rpr.group(0) if rpr else ''}<a:t>{page}</a:t></a:r>"

    return _SLIDE_NUM_FIELD_RE.sub(repl, slide_xml)


def _structural_parts(names: set[str]) -> set[str]:
    keep: set[str] = set()
    for name in names:
        if name in _DROP_FILES:
            continue
        if name.startswith(_DROP_PREFIXES):
            continue
        if _SLIDE_PART_RE.match(name):
            continue
        keep.add(name)
    keep.update({CONTENT_TYPES, ROOT_RELS, PRESENTATION_PART, PRESENTATION_RELS})
    return keep


def build_slice(deck: Path, pages: list[int], destination: Path) -> Path:
    """生成只含 ``pages`` 的切片 pptx，写到 ``destination``。"""
    if not pages:
        raise ValueError("pages 不能为空")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(deck)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PptError("not_pptx", f"无法读取 deck：{deck.name}（{exc}）") from exc

    with archive:
        names = set(archive.namelist())
        presentation, by_page, page_of = _page_map(archive)

        missing = [page for page in pages if page not in by_page]
        if missing:
            raise PptError(
                "slide_out_of_range",
                f"第 {missing[0]} 页不存在，该 deck 共 {len(by_page)} 页",
            )

        kept = _structural_parts(names)
        for page in pages:
            _entry, slide = by_page[page]
            queue = [slide]
            while queue:
                part = queue.pop()
                if part in kept or part not in names:
                    continue
                kept.add(part)
                rels = _rels_part(part)
                if rels in names:
                    kept.add(rels)
                    queue.extend(
                        target
                        for _tag, target, external in _parse_rels(
                            archive.read(rels).decode("utf-8"), rels
                        )
                        if not external
                    )

        sld_ids = "".join(by_page[page][0] for page in pages)
        original_lst = re.search(r"<p:sldIdLst>.*?</p:sldIdLst>", presentation, re.S)
        assert original_lst is not None
        presentation = presentation.replace(
            original_lst.group(0), f"<p:sldIdLst>{sld_ids}</p:sldIdLst>"
        )

        try:
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
                for name in sorted(kept):
                    if name == PRESENTATION_PART:
                        out.writestr(name, presentation.encode("utf-8"))
                        continue
                    if name.endswith(".rels"):
                        xml = archive.read(name).decode("utf-8")
                        out.writestr(name, _filter_rels(xml, name, kept).encode("utf-8"))
                        continue
                    data = archive.read(name)
                    page = page_of.get(name)
                    if page is not None and b"slidenum" in data:
                        data = _fix_slide_number(data.decode("utf-8"), page).encode("utf-8")
                    out.writestr(name, data)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise PptError("render_failed", f"切片写入失败：{exc}") from exc

    return destination