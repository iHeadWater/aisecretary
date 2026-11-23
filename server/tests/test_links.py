"""事务关联（link）与合并（merge）测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.app import config
from server.app.database import get_connection, init_db
from server.app.models import RelationType
from server.app.schemas import TransactionCreate
from server.app.storage import (
    create_transaction,
    delete_transaction,
    get_links,
    get_transaction,
    link_transactions,
    list_transactions,
    merge_transactions,
    summarize_transactions,
    unlink_transactions,
)


@pytest.fixture()
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config.settings, "database_path", tmp_path / "links.sqlite")
    init_db()
    with get_connection() as connection:
        yield connection


def _make(conn, title: str, **kwargs) -> dict:
    payload = TransactionCreate(title=title, **kwargs)
    return create_transaction(conn, payload)


class TestLink:
    def test_link_and_read_back(self, conn) -> None:
        parent = _make(conn, "澜沧江投标")
        child = _make(conn, "资质材料")

        result = link_transactions(conn, child["id"], parent["id"], "part_of")
        assert result["created"] is True
        assert result["relation"] == "part_of"

        links = get_links(conn, child["id"])
        assert len(links) == 1
        assert links[0]["id"] == parent["id"]
        assert links[0]["title"] == "澜沧江投标"
        assert links[0]["relation"] == "part_of"
        assert links[0]["direction"] == "out"

    def test_inverse_relation_from_the_other_side(self, conn) -> None:
        parent = _make(conn, "澜沧江投标")
        child = _make(conn, "资质材料")
        link_transactions(conn, child["id"], parent["id"], "part_of")

        parent_links = get_links(conn, parent["id"])
        assert parent_links[0]["relation"] == "has_part"
        assert parent_links[0]["direction"] == "in"

    def test_blocks_inverse(self, conn) -> None:
        blocker = _make(conn, "等财务给数")
        blocked = _make(conn, "交自查表")
        link_transactions(conn, blocker["id"], blocked["id"], "blocks")

        assert get_links(conn, blocked["id"])[0]["relation"] == "blocked_by"

    def test_related_is_symmetric_on_unlink(self, conn) -> None:
        first = _make(conn, "出国访学签证")
        second = _make(conn, "联系国外导师")
        link_transactions(conn, first["id"], second["id"], "related")

        # 从另一侧删除也能删掉
        assert unlink_transactions(conn, second["id"], first["id"], "related")["removed"] == 1
        assert get_links(conn, first["id"]) == []

    def test_idempotent(self, conn) -> None:
        first = _make(conn, "A")
        second = _make(conn, "B")
        assert link_transactions(conn, first["id"], second["id"], "related")["created"] is True
        assert link_transactions(conn, first["id"], second["id"], "related")["created"] is False
        assert len(get_links(conn, first["id"])) == 1

    def test_self_link_rejected(self, conn) -> None:
        only = _make(conn, "A")
        with pytest.raises(ValueError, match="自己"):
            link_transactions(conn, only["id"], only["id"], "related")

    def test_unknown_id_rejected(self, conn) -> None:
        only = _make(conn, "A")
        with pytest.raises(ValueError, match="事务不存在"):
            link_transactions(conn, only["id"], "nope", "related")

    def test_invalid_relation_rejected(self, conn) -> None:
        first = _make(conn, "A")
        second = _make(conn, "B")
        with pytest.raises(ValueError, match="无效的关联类型"):
            link_transactions(conn, first["id"], second["id"], "depends_on")

    def test_unlink_all_relations_between_pair(self, conn) -> None:
        first = _make(conn, "A")
        second = _make(conn, "B")
        link_transactions(conn, first["id"], second["id"], "related")
        link_transactions(conn, first["id"], second["id"], "part_of")

        assert unlink_transactions(conn, first["id"], second["id"])["removed"] == 2
        assert get_links(conn, first["id"]) == []

    def test_delete_cleans_links(self, conn) -> None:
        first = _make(conn, "A")
        second = _make(conn, "B")
        link_transactions(conn, first["id"], second["id"], "related")

        delete_transaction(conn, second["id"])
        assert get_links(conn, first["id"]) == []

    def test_list_by_linked_to(self, conn) -> None:
        hub = _make(conn, "HUB")
        first = _make(conn, "A")
        second = _make(conn, "C")
        link_transactions(conn, first["id"], hub["id"], "part_of")
        link_transactions(conn, hub["id"], second["id"], "related")

        linked = list_transactions(conn, linked_to=hub["id"])
        assert {row["title"] for row in linked} == {"A", "C"}


class TestMerge:
    def test_merge_moves_notes_and_links(self, conn) -> None:
        target = _make(conn, "澜沧江投标", notes="主记录")
        source = _make(conn, "澜沧江投标（重复录入）", notes="旧备注")
        other = _make(conn, "叶磊讲课")
        link_transactions(conn, source["id"], other["id"], "related")

        result = merge_transactions(conn, source["id"], target["id"])

        assert result["merged"] is True
        assert result["repointed_links"] == 1
        assert "旧备注" in result["target"]["notes"]
        assert "主记录" in result["target"]["notes"]
        assert "重复录入" in result["target"]["notes"]

        # 关联边已转到 target 上
        assert [item["id"] for item in get_links(conn, target["id"])] == [other["id"]]
        assert get_links(conn, source["id"]) == []

    def test_merged_hidden_from_list_and_summary(self, conn) -> None:
        target = _make(conn, "主")
        source = _make(conn, "重复")
        merge_transactions(conn, source["id"], target["id"])

        titles = [row["title"] for row in list_transactions(conn)]
        assert titles == ["主"]

        summary = summarize_transactions(conn)
        assert summary["total"] == 1

        # 显式要求时仍能看到
        assert len(list_transactions(conn, include_merged=True)) == 2

    def test_merged_record_kept_with_pointer(self, conn) -> None:
        target = _make(conn, "主")
        source = _make(conn, "重复")
        merge_transactions(conn, source["id"], target["id"])

        kept = get_transaction(conn, source["id"])
        assert kept is not None
        assert kept["merged_into"] == target["id"]

    def test_merge_self_rejected(self, conn) -> None:
        only = _make(conn, "A")
        with pytest.raises(ValueError, match="自己"):
            merge_transactions(conn, only["id"], only["id"])

    def test_merge_unknown_id(self, conn) -> None:
        only = _make(conn, "A")
        with pytest.raises(ValueError, match="事务不存在"):
            merge_transactions(conn, only["id"], "nope")

    def test_double_merge_rejected(self, conn) -> None:
        first = _make(conn, "主")
        second = _make(conn, "次")
        third = _make(conn, "再次")
        merge_transactions(conn, second["id"], first["id"])
        with pytest.raises(ValueError, match="已合并"):
            merge_transactions(conn, second["id"], third["id"])

    def test_merge_drops_self_loop_when_pair_linked(self, conn) -> None:
        target = _make(conn, "主")
        source = _make(conn, "重复")
        link_transactions(conn, source["id"], target["id"], "related")

        result = merge_transactions(conn, source["id"], target["id"])

        # source→target 这条边会变成 target→target，应被丢弃
        assert result["repointed_links"] == 0
        assert get_links(conn, target["id"]) == []


class TestRelationEnum:
    def test_values(self) -> None:
        assert {r.value for r in RelationType} == {"part_of", "blocks", "related"}