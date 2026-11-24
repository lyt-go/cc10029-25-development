"""集成测试：恢复范围看板端到端验证。

覆盖任务验收链路：一完整一缺片两个卷查看同批覆盖概览 → 发起重放核对实际数据 →
补回缺片后再查询 → 比较可取回范围与上一次重放引用的卷 → 更换版本后回查旧卷。
"""
from __future__ import annotations

import time

import pytest

from app.services.recovery_scope import RecoveryScopeService
from app.store import store


@pytest.fixture(autouse=True)
def cleanup():
    """每个测试前重置store数据，确保测试隔离。"""
    from app.seed import SEED_ROWS
    store._tables = {
        name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
    }
    yield


def _unique_batch() -> str:
    return f"BATC-TEST-{int(time.time() * 1000) % 10_000_000}"


class TestSeedScenarioDashboard:
    """种子场景：同一历史批次出现在两个归档卷里，旧卷已校验、第二卷缺一片。"""

    def test_seed_batch_shows_two_volumes_and_one_missing_piece(self):
        svc = RecoveryScopeService()
        board = svc.recovery_board("BATC-2024-11")

        # 覆盖概览：两个卷，HIST-0001 完整，HIST-0002 缺一片
        coverage = {row["volume"]: row for row in board["coverage"]}
        assert coverage["HIST-0001"]["recoverable"] == 3
        assert coverage["HIST-0001"]["missing"] == 0
        assert coverage["HIST-0001"]["verify_state"] == "已校验"
        assert coverage["HIST-0002"]["recoverable"] == 2
        assert coverage["HIST-0002"]["missing"] == 1

        # 缺片单独记录
        assert len(board["missing"]) == 1
        assert board["missing"][0]["分片编号"] == "BATC-2024-11-P3"
        assert board["missing"][0]["归档卷"] == "HIST-0002"

    def test_each_recoverable_piece_shows_version_batch_and_credential(self):
        svc = RecoveryScopeService()
        board = svc.recovery_board("BATC-2024-11")
        assert len(board["recoverable"]) == 5
        for piece in board["recoverable"]:
            assert piece["归档版本"] in {"v1.0", "v2.0"}
            assert piece["来源批次"] == "BATC-2024-11"
            assert piece["校验凭据"].startswith("SHA256:")

    def test_seed_batch_has_complete_lineage_association(self):
        svc = RecoveryScopeService()
        board = svc.recovery_board("BATC-2024-11")
        assert board["lineage"]["active_code"] == "TRAN-9101"
        # 旧卷分片已带血缘，新卷分片等待关联
        old = [p for p in board["recoverable"] if p["归档卷"] == "HIST-0001"]
        assert all(p["血缘链路"] == "TRAN-9101" for p in old)


class TestPublishAndCoverage:
    """发布一完整一缺片两个卷，查看同一批的覆盖概览。"""

    def test_two_volumes_coverage_overview(self):
        svc = RecoveryScopeService()
        batch = _unique_batch()
        svc.publish_volume("HIST-A", batch, "v1.0", piece_count=3, verified=True, lineage_code="TRAN-A")
        svc.publish_volume("HIST-B", batch, "v2.0", piece_count=3, missing=[2])

        board = svc.recovery_board(batch)
        coverage = {row["volume"]: row for row in board["coverage"]}
        assert coverage["HIST-A"]["total"] == 3
        assert coverage["HIST-A"]["recoverable"] == 3
        assert coverage["HIST-B"]["missing"] == 1
        assert len(board["recoverable"]) == 5
        assert len(board["missing"]) == 1
        assert board["missing"][0]["分片编号"] == f"{batch}-P2"

    def test_version_change_keeps_old_volume_queryable(self):
        svc = RecoveryScopeService()
        batch = _unique_batch()
        svc.publish_volume("HIST-V", batch, "v1.0", piece_count=2, verified=True)
        svc.publish_volume("HIST-V", batch, "v2.0", piece_count=3, verified=True)

        # 当前看板只看新版本
        board = svc.recovery_board(batch)
        assert {p["归档版本"] for p in board["recoverable"]} == {"v2.0"}
        assert len(board["superseded"]) == 2
        assert {p["归档版本"] for p in board["superseded"]} == {"v1.0"}

        # 更换版本后仍能回查先前用过的卷
        history = svc.version_history("HIST-V")
        assert {row["归档版本"] for row in history} == {"v1.0", "v2.0"}
        old_rows = [row for row in history if row["归档版本"] == "v1.0"]
        assert all(row["status"] == "已替换" for row in old_rows)


class TestReplayReadsActualData:
    """发起重放：依照经确认的成员范围读取实际数据，记下每片来自哪个卷。"""

    def test_replay_reads_confirmed_ranges_and_records_volume(self):
        svc = RecoveryScopeService()
        batch = _unique_batch()
        svc.publish_volume("HIST-OLD", batch, "v1.0", piece_count=3, verified=True)
        svc.publish_volume("HIST-NEW", batch, "v2.0", piece_count=3, missing=[3])

        result = svc.replay_batch(batch)
        assert "error" not in result
        # 缺片不参与重放：3 片均来自经确认的可恢复范围
        assert len(result["pieces"]) == 3
        assert result["all_verified"]
        # 每片都记下来源卷与采用的校验凭据
        for piece in result["pieces"]:
            assert piece["volume"] in {"HIST-OLD", "HIST-NEW"}
            assert piece["credential"].startswith("SHA256:")
            assert piece["records"] == 5
        # 同一片两卷都有时优先已校验的旧卷
        p1 = [p for p in result["pieces"] if p["piece_code"] == f"{batch}-P1"][0]
        assert p1["volume"] == "HIST-OLD"
        # 缺的那片只能由旧卷提供
        p3 = [p for p in result["pieces"] if p["piece_code"] == f"{batch}-P3"][0]
        assert p3["volume"] == "HIST-OLD"
        # 实际数据落盘且条数正确
        assert result["total_records"] == 15

    def test_replay_without_recoverable_pieces_fails(self):
        svc = RecoveryScopeService()
        result = svc.replay_batch(_unique_batch())
        assert "error" in result


class TestRestoreAndCompare:
    """补回缺片后再查询，比较可取回范围和上一次重放引用的卷。"""

    def test_restore_piece_expands_recoverable_range(self):
        svc = RecoveryScopeService()
        batch = _unique_batch()
        svc.publish_volume("HIST-C", batch, "v1.0", piece_count=3, verified=True)
        svc.publish_volume("HIST-D", batch, "v2.0", piece_count=3, missing=[2])

        # 先重放一次：HIST-D 的 P2 缺片，只能由 HIST-C 提供
        first = svc.replay_batch(batch)
        p2_first = [p for p in first["pieces"] if p["piece_code"] == f"{batch}-P2"][0]
        assert p2_first["volume"] == "HIST-C"

        # 补回缺片
        missing_entry = svc.recovery_board(batch)["missing"][0]
        restored = svc.restore_piece(missing_entry["id"])
        assert restored["status"] == "可恢复"
        assert restored["credential"].startswith("SHA256:")

        # 再查询：可取回范围多出一片，缺片清单清空
        board = svc.recovery_board(batch)
        assert len(board["recoverable"]) == 6
        assert len(board["missing"]) == 0

        # 上一次重放引用的卷仍可回查对比
        last = board["last_replay"]
        assert last is not None
        assert last["replay_code"] == first["replay_code"]
        assert set(last["volumes"]) == set(first["volumes_used"])

        # 补回后再次重放：P2 仍优先已校验卷，且两次重放的卷选择可对比
        second = svc.replay_batch(batch)
        assert len(second["pieces"]) == 3
        board_after = svc.recovery_board(batch)
        assert board_after["last_replay"]["replay_code"] == second["replay_code"]

    def test_replay_history_records_each_fetch_volume(self):
        svc = RecoveryScopeService()
        batch = _unique_batch()
        svc.publish_volume("HIST-E", batch, "v1.0", piece_count=2, verified=True)
        svc.replay_batch(batch)
        history = svc.replay_history(batch)
        assert len(history) == 2
        assert all(rec["volume"] == "HIST-E" for rec in history)
        assert all(rec["verified"] for rec in history)


class TestLineageSync:
    """传输血缘关联并展示恢复范围清单。"""

    def test_sync_lineage_links_entries_without_chain(self):
        svc = RecoveryScopeService()
        # 种子批次里 HIST-0002 的分片尚未关联血缘
        result = svc.sync_lineage("BATC-2024-11")
        assert result["lineage_code"] == "TRAN-9101"
        assert result["linked"] >= 2
        board = svc.recovery_board("BATC-2024-11")
        assert all(p["血缘链路"] == "TRAN-9101" for p in board["recoverable"])

    def test_sync_lineage_without_active_chain(self):
        svc = RecoveryScopeService()
        result = svc.sync_lineage(_unique_batch())
        assert result["linked"] == 0


class TestRecoveryScopeSnapshot:
    """模块级快照可调用。"""

    def test_domain_snapshot(self):
        snapshot = RecoveryScopeService().domain_snapshot()
        assert snapshot["module"] == "recovery_scope"
        assert snapshot["count"] == 6
        assert snapshot["by_status"]["缺片待补"] == 1
