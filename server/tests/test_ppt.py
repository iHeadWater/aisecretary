"""PPT 能力测试：路径校验、内容提取、状态、渲染。

渲染用例在没有 soffice/pdftoppm 的环境（如 macOS 开发机）自动跳过；
容器内 ``docker build --target test`` 会真正跑 LO。
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from pathlib import Path

import pytest

from server.app import config
from server.app.ppt import render, service
from server.app.ppt.errors import PptError
from server.app.ppt.paths import resolve_deck, slide_count

# 1x1 透明 PNG，用作 fixture 里的图片
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

SLIDE_W = 13.333
SLIDE_H = 7.5


def _build_deck(path: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    # 1: 标题 + 正文 + 备注
    first = prs.slides.add_slide(prs.slide_layouts[1])
    first.shapes.title.text = "第 1 页 标题"
    body = first.placeholders[1]
    body.text = "第一行正文"
    body.text_frame.add_paragraph().text = "第二行正文"
    first.notes_slide.notes_text_frame.text = "这是演讲者备注"

    # 2: 表格
    second = prs.slides.add_slide(prs.slide_layouts[5])
    second.shapes.title.text = "带表格的一页"
    table = second.shapes.add_table(
        2, 2, Inches(1), Inches(2), Inches(6), Inches(1.5)
    ).table
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "数值"
    table.cell(1, 0).text = "精度"
    table.cell(1, 1).text = "0.91"

    # 3: 图片
    third = prs.slides.add_slide(prs.slide_layouts[5])
    third.shapes.title.text = "带图片的一页"
    third.shapes.add_picture(
        io.BytesIO(PNG_1PX), Inches(1), Inches(2), Inches(2), Inches(2)
    )
    textbox = third.shapes.add_textbox(Inches(4), Inches(2), Inches(4), Inches(1))
    textbox.text_frame.text = "图片旁的说明"
    textbox.text_frame.paragraphs[0].runs[0].font.size = Pt(18)

    prs.save(str(path))
    return path


@pytest.fixture()
def deck_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "decks"
    root.mkdir()
    deck = _build_deck(root / "测试 deck.pptx")
    monkeypatch.setattr(config.settings, "ppt_roots", str(root))
    monkeypatch.setattr(config.settings, "ppt_out_dir", tmp_path / "out")
    return deck


@pytest.fixture()
def clean_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test_ppt.sqlite"
    monkeypatch.setattr(config.settings, "database_path", db)
    return db


class TestPaths:
    def test_resolve_valid(self, deck_dir: Path) -> None:
        resolved = resolve_deck(str(deck_dir))
        assert resolved == deck_dir.resolve()
        assert slide_count(resolved) == 3

    def test_missing_file(self, deck_dir: Path) -> None:
        with pytest.raises(PptError) as exc:
            resolve_deck(str(deck_dir.parent / "nope.pptx"))
        assert exc.value.code == "deck_not_found"

    def test_outside_roots(self, deck_dir: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside.pptx"
        outside.write_bytes(deck_dir.read_bytes())
        with pytest.raises(PptError) as exc:
            resolve_deck(str(outside))
        assert exc.value.code == "path_not_allowed"

    def test_traversal(self, deck_dir: Path, tmp_path: Path) -> None:
        # 带 .. 但结论仍落在根目录内：允许
        sneaky = deck_dir.parent / ".." / "decks" / deck_dir.name
        assert resolve_deck(str(sneaky)) == deck_dir

        # 带 .. 逃到根目录外：拒绝
        outside = tmp_path / "outside.pptx"
        outside.write_bytes(deck_dir.read_bytes())
        escape = deck_dir.parent / ".." / "outside.pptx"
        with pytest.raises(PptError) as exc:
            resolve_deck(str(escape))
        assert exc.value.code == "path_not_allowed"

    def test_wrong_extension(self, deck_dir: Path, tmp_path: Path) -> None:
        fake = tmp_path / "decks" / "fake.pdf"
        fake.write_bytes(b"%PDF-1.4")
        with pytest.raises(PptError) as exc:
            resolve_deck(str(fake))
        assert exc.value.code == "not_pptx"

    def test_not_a_real_pptx(self, deck_dir: Path) -> None:
        fake = deck_dir.parent / "broken.pptx"
        fake.write_bytes(b"not a zip")
        with pytest.raises(PptError) as exc:
            resolve_deck(str(fake))
        assert exc.value.code == "not_pptx"


class TestExtract:
    def test_slide_text_and_notes(self, deck_dir: Path, clean_db: Path) -> None:
        data = service.get_slide(1, str(deck_dir))
        assert data["page"] == 1
        assert data["slide_count"] == 3
        assert data["title"] == "第 1 页 标题"
        assert "第一行正文" in data["text"]
        assert "第二行正文" in data["text"]
        assert data["notes"] == "这是演讲者备注"
        assert data["image_count"] == 0

    def test_slide_table(self, deck_dir: Path, clean_db: Path) -> None:
        data = service.get_slide(2, str(deck_dir))
        assert len(data["tables"]) == 1
        table = data["tables"][0]
        assert table["rows"] == 2 and table["cols"] == 2
        assert table["data"][0][0] == "指标"
        assert table["data"][1][1] == "0.91"

    def test_slide_picture(self, deck_dir: Path, clean_db: Path) -> None:
        data = service.get_slide(3, str(deck_dir))
        assert data["image_count"] == 1
        assert any("图片旁的说明" in line for line in data["text"])

    def test_page_out_of_range(self, deck_dir: Path, clean_db: Path) -> None:
        with pytest.raises(PptError) as exc:
            service.get_slide(99, str(deck_dir))
        assert exc.value.code == "slide_out_of_range"
        assert exc.value.extra["slide_count"] == 3

    def test_outline(self, deck_dir: Path, clean_db: Path) -> None:
        rows = service.outline(str(deck_dir))
        assert [row["page"] for row in rows] == [1, 2, 3]
        assert rows[0]["title"] == "第 1 页 标题"
        assert rows[1]["title"] == "带表格的一页"


class TestDeckState:
    def test_use_then_get(self, deck_dir: Path, clean_db: Path) -> None:
        used = service.use_deck(str(deck_dir))
        assert used["slide_count"] == 3
        assert used["file_name"] == deck_dir.name
        current = service.get_deck()
        assert current["path"] == str(deck_dir)

    def test_no_deck(self, clean_db: Path) -> None:
        with pytest.raises(PptError) as exc:
            service.get_deck()
        assert exc.value.code == "no_deck"

    def test_deleted_deck_resets_state(
        self, deck_dir: Path, clean_db: Path, tmp_path: Path
    ) -> None:
        service.use_deck(str(deck_dir))
        deck_dir.unlink()
        with pytest.raises(PptError) as exc:
            service.get_deck()
        assert exc.value.code == "no_deck"
        # 状态已清空，再取仍然是 no_deck
        with pytest.raises(PptError):
            service.get_deck()


@pytest.mark.skipif(
    not render.tools_available(), reason="需要 soffice + pdftoppm（容器内才具备）"
)
class TestRender:
    def test_render_first_page(self, deck_dir: Path, clean_db: Path) -> None:
        result = service.render_slide(1, str(deck_dir), 150)
        assert Path(result["path"]).is_file()
        assert result["page"] == 1
        assert result["slide_count"] == 3
        assert result["width"] in (2000, 2001)
        assert result["height"] in (1125, 1126)
        assert result["cached"] is False
        assert result["ms"] < 20_000

    def test_second_call_is_cached(self, deck_dir: Path, clean_db: Path) -> None:
        first = service.render_slide(2, str(deck_dir), 150)
        second = service.render_slide(2, str(deck_dir), 150)
        assert second["path"] == first["path"]
        assert second["cached"] is True
        assert second["ms"] == 0

    def test_dpi_validation(self, deck_dir: Path, clean_db: Path) -> None:
        with pytest.raises(PptError) as exc:
            service.render_slide(1, str(deck_dir), 10)
        assert exc.value.code == "invalid_dpi"


class TestRenderUnavailable:
    @pytest.mark.skipif(
        render.tools_available(), reason="本机有 soffice，测不到缺依赖的分支"
    )
    def test_render_without_tools(self, deck_dir: Path, clean_db: Path) -> None:
        with pytest.raises(PptError) as exc:
            service.render_slide(1, str(deck_dir), 150)
        assert exc.value.code == "render_unavailable"


class TestCachePrune:
    def test_prune_old_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "ppt_cache_max_age_days", 7)
        stale = tmp_path / "stale.png"
        fresh = tmp_path / "fresh.png"
        stale.write_bytes(b"png")
        fresh.write_bytes(b"png")
        past = time.time() - 8 * 86400
        os.utime(stale, (past, past))

        assert render.prune_cache(tmp_path) == 1
        assert not stale.exists()
        assert fresh.exists()

    def test_prune_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "ppt_cache_max_age_days", 0)
        stale = tmp_path / "stale.png"
        stale.write_bytes(b"png")
        past = time.time() - 99 * 86400
        os.utime(stale, (past, past))

        assert render.prune_cache(tmp_path) == 0
        assert stale.exists()


class TestMcpPptTools:
    def test_bad_path_returns_json_error(self, clean_db: Path) -> None:
        from server.app import mcp_server

        payload = json.loads(mcp_server.tool_ppt_get_slide(1, "/nope/x.pptx"))
        assert payload["error"] == "deck_not_found"

    def test_mcp_tools_are_registered(self) -> None:
        import asyncio

        from server.app.mcp_server import mcp

        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        assert {
            "ppt_use_deck",
            "ppt_get_deck",
            "ppt_outline",
            "ppt_get_slide",
            "ppt_render_slide",
        } <= names


class TestSlice:
    def test_slice_keeps_only_requested_page(self, deck_dir: Path) -> None:
        import zipfile

        from server.app.ppt import slice as slice_builder

        destination = deck_dir.parent / "slice.pptx"
        slice_builder.build_slice(deck_dir, [2], destination)

        with zipfile.ZipFile(destination) as archive:
            names = set(archive.namelist())
            presentation = archive.read("ppt/presentation.xml").decode("utf-8")
            rels = archive.read("ppt/_rels/presentation.xml.rels").decode("utf-8")

        assert "<p:sldId " in presentation
        assert presentation.count("<p:sldId ") == 1
        assert sum(1 for name in names if name.startswith("ppt/slides/slide")) == 1
        # 结构件必须保留，否则 LO 拒绝加载
        assert "ppt/slideMasters/slideMaster1.xml" in names
        assert "[Content_Types].xml" in names
        assert names & {n for n in names if n.startswith("ppt/slideLayouts/slideLayout")}
        # 表页没有图片，切片里不应出现 media
        assert not [n for n in names if n.startswith("ppt/media/")]
        # 目标页自己的 rels 必须指向真实存在的 layout
        with zipfile.ZipFile(destination) as archive:
            slide_rels = archive.read("ppt/slides/_rels/slide2.xml.rels").decode("utf-8")
        assert "slideLayout" in slide_rels
        assert "slideLayout1.xml" in slide_rels or "slideLayouts/" in slide_rels

    def test_slice_includes_page_media(self, deck_dir: Path) -> None:
        import zipfile

        from server.app.ppt import slice as slice_builder

        destination = deck_dir.parent / "slice-media.pptx"
        slice_builder.build_slice(deck_dir, [3], destination)
        with zipfile.ZipFile(destination) as archive:
            media = [n for n in archive.namelist() if n.startswith("ppt/media/")]
        assert media, "带图片的页必须把图片带进切片"

    def test_slice_multi_page(self, deck_dir: Path) -> None:
        import zipfile

        from server.app.ppt import slice as slice_builder
        from server.app.ppt.paths import slide_count

        destination = deck_dir.parent / "slice-multi.pptx"
        slice_builder.build_slice(deck_dir, [1, 2, 3], destination)
        assert slide_count(destination) == 3
        with zipfile.ZipFile(destination) as archive:
            names = set(archive.namelist())
        # 多页切片要带上每一页的媒体
        assert [n for n in names if n.startswith("ppt/media/")]

    def test_slice_out_of_range(self, deck_dir: Path) -> None:
        from server.app.ppt import slice as slice_builder

        with pytest.raises(PptError) as exc:
            slice_builder.build_slice(deck_dir, [9], deck_dir.parent / "bad.pptx")
        assert exc.value.code == "slide_out_of_range"

    def test_slide_number_field_is_materialised(self) -> None:
        from server.app.ppt.slice import _fix_slide_number

        xml = (
            '<a:p><a:fld id="{X}" type="slidenum"><a:rPr lang="zh-CN" sz="1400" b="1"/>'
            "<a:t>1</a:t></a:fld></a:p>"
        )
        fixed = _fix_slide_number(xml, 9)
        assert "slidenum" not in fixed
        assert '<a:t>9</a:t>' in fixed
        assert "<a:rPr" in fixed


class TestPageGrouping:
    def test_single_page(self) -> None:
        assert service._group_pages([5], 8) == [[5]]

    def test_consecutive_pages_merge(self) -> None:
        assert service._group_pages([5, 6, 7, 8], 8) == [[5, 6, 7, 8]]

    def test_gap_splits_groups(self) -> None:
        assert service._group_pages([5, 6, 9], 8) == [[5, 6], [9]]

    def test_batch_cap(self) -> None:
        groups = service._group_pages(list(range(1, 12)), 8)
        assert groups == [list(range(1, 9)), [9, 10, 11]]


class TestParsePages:
    def test_single(self) -> None:
        assert service.parse_pages("5") == [5]

    def test_list(self) -> None:
        assert service.parse_pages("5,6,9") == [5, 6, 9]

    def test_range(self) -> None:
        assert service.parse_pages("5-8") == [5, 6, 7, 8]

    def test_mixed_and_spaces(self) -> None:
        assert service.parse_pages(" 5-6 , 9 ") == [5, 6, 9]

    def test_reversed_range(self) -> None:
        assert service.parse_pages("8-6") == [6, 7, 8]

    def test_invalid(self) -> None:
        for spec in ("", "abc", "5-", "3,x"):
            with pytest.raises(PptError) as exc:
                service.parse_pages(spec)
            assert exc.value.code == "invalid_page"

    def test_too_many(self) -> None:
        with pytest.raises(PptError) as exc:
            service.parse_pages("1-40")
        assert exc.value.code == "too_many_pages"


@pytest.mark.skipif(
    not render.tools_available(), reason="需要 soffice + pdftoppm（容器内才具备）"
)
class TestRenderBatch:
    def test_render_two_pages(self, deck_dir: Path, clean_db: Path) -> None:
        results = service.render_pages([1, 2], str(deck_dir), 150)
        assert [item["page"] for item in results] == [1, 2]
        for item in results:
            assert Path(item["path"]).is_file()
            assert item["cached"] is False
        assert results[0]["path"] != results[1]["path"]

    def test_second_call_is_cached(self, deck_dir: Path, clean_db: Path) -> None:
        service.render_pages([1, 3], str(deck_dir), 150)
        again = service.render_pages([1, 3], str(deck_dir), 150)
        assert all(item["cached"] is True for item in again)

    def test_duplicate_pages(self, deck_dir: Path, clean_db: Path) -> None:
        results = service.render_pages([2, 2], str(deck_dir), 150)
        assert [item["page"] for item in results] == [2, 2]
        assert results[0]["path"] == results[1]["path"]

    def test_slice_disabled_falls_back(self, deck_dir: Path, clean_db: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "ppt_slice_enabled", False)
        result = service.render_slide(2, str(deck_dir), 150)
        assert Path(result["path"]).is_file()
