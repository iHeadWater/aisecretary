"""PPT 能力测试：路径校验、内容提取、状态、渲染。

渲染用例在没有 soffice/pdftoppm 的环境（如 macOS 开发机）自动跳过；
容器内 ``docker build --target test`` 会真正跑 LO。
"""

from __future__ import annotations

import base64
import io
import json
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
