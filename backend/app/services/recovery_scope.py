"""恢复范围看板领域服务：按批次汇总归档卷分片的可恢复范围、缺片与版本血缘。

本模块读取批次归档卷与传输血缘数据，把同一历史批次在多个归档卷中的分片
整理成恢复范围清单：
- 可取回的每片都标注归档版本、来源批次与历史重放请求采用的校验凭据；
- 缺片与已可恢复的范围分别记录；
- 归档卷更换版本后，先前用过的卷版本仍保留可回查；
- 历史重放依照经确认的成员范围读取实际数据，并记下每片来自哪个卷。
"""
from __future__ import annotations

import time
from typing import Any

from app.recovery_pieces import parse_member_range, piece_credential, piece_records, records_checksum
from app.services.base import BaseModuleService
from app.store import store

RECOVERABLE = "可恢复"
MISSING = "缺片待补"
SUPERSEDED = "已替换"


class RecoveryScopeService(BaseModuleService):
    MODULE = "recovery_scope"
    ENTITY = "恢复范围"
    OPERATION_TERM = "恢复"
    LIST_FIELDS = ["看板编号", "来源批次", "归档卷", "归档版本", "分片编号", "成员范围",
                   "校验凭据", "血缘链路", "卷校验状态"]
    REQUIRED_FIELDS = ["看板编号", "来源批次", "归档卷", "分片编号"]
    STATUS_ORDER = ["待确认", "可恢复", "缺片待补", "已替换"]
    ACTION_RULES = {"确认范围": "可恢复", "标记缺片": "缺片待补", "补回缺片": "可恢复", "标记替换": "已替换"}
    NEGATIVE_ACTIONS = ["标记缺片"]

    # -- 分片物化与凭据 --

    def _piece_file(self, piece_code: str):
        """分片实际数据文件路径：data/recovery/pieces/<分片编号>.jsonl。"""
        return self._data_dir("recovery/pieces") / f"{piece_code}.jsonl"

    def _materialize_piece(self, entry: dict[str, Any]) -> str:
        """确保分片实际数据落盘，并把校验凭据刷新为与数据一致的值。"""
        piece_file = self._piece_file(entry["分片编号"])
        if not piece_file.exists():
            records = piece_records(entry["来源批次"], entry["分片编号"], entry.get("成员范围", "行1-1"))
            self._write_jsonl(piece_file, records)
        credential = piece_credential(entry["来源批次"], entry["分片编号"], entry.get("成员范围", "行1-1"))
        if entry.get("校验凭据") != credential:
            entry["校验凭据"] = credential
        return credential

    # -- 卷版本发布与缺片补回 --

    def publish_volume(
        self,
        volume_code: str,
        batch_code: str,
        version: str,
        piece_count: int = 3,
        missing: list[int] | None = None,
        verified: bool = False,
        lineage_code: str = "",
    ) -> dict[str, Any]:
        """发布一卷对某批次的一个归档版本：旧版本分片标记替换，新版本分片登记入清单。

        更换版本不会删除先前版本的分片记录，只是置为「已替换」，
        之后仍可按卷回查历史版本。
        """
        missing = missing or []
        superseded = 0
        for row in store.rows(self.MODULE):
            if row.get("归档卷") == volume_code and row.get("来源批次") == batch_code \
                    and row.get("status") != SUPERSEDED:
                self.run_action(int(row["id"]), "标记替换")
                superseded += 1

        entries = []
        for idx in range(1, piece_count + 1):
            piece_code = f"{batch_code}-P{idx}"
            start = (idx - 1) * 5 + 1
            member_range = f"行{start}-{start + 4}"
            board_code = f"RECO-{volume_code}-{version}-{idx}"
            values = {
                "看板编号": board_code,
                "来源批次": batch_code,
                "归档卷": volume_code,
                "归档版本": version,
                "分片编号": piece_code,
                "成员范围": member_range,
                "校验凭据": "",
                "血缘链路": lineage_code,
                "卷校验状态": "已校验" if verified else "待校验",
            }
            entry, missing_fields = self.create_entry(values)
            if entry is None:
                raise ValueError(f"登记恢复范围失败: {missing_fields}")
            entry["登记时间"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            if idx in missing:
                self.run_action(entry["id"], "标记缺片")
            else:
                self.run_action(entry["id"], "确认范围")
                self._materialize_piece(entry)
            entries.append(entry)

        self._write_jsonl(
            self._data_dir("events") / "recovery_publish_log.jsonl",
            [{"action": "publish_volume", "volume": volume_code, "batch": batch_code,
              "version": version, "pieces": piece_count, "missing": missing,
              "verified": verified, "superseded": superseded, "at": time.time()}]
        )
        return {"volume": volume_code, "batch": batch_code, "version": version,
                "pieces": len(entries), "missing": list(missing), "superseded": superseded}

    def restore_piece(self, entry_id: int) -> dict[str, Any]:
        """补回缺片：重新物化分片实际数据、刷新校验凭据并置为可恢复。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return {"error": f"恢复范围 {entry_id} 不存在"}
        if entry.get("status") != MISSING:
            return {"error": f"分片 {entry.get('分片编号')} 当前不是缺片状态", "entry": entry}
        credential = self._materialize_piece(entry)
        final_entry, msg = self.run_action(entry_id, "补回缺片")
        self._write_jsonl(
            self._data_dir("events") / "recovery_restore_log.jsonl",
            [{"action": "restore_piece", "piece_code": entry["分片编号"],
              "volume": entry["归档卷"], "version": entry["归档版本"],
              "batch": entry["来源批次"], "credential": credential, "at": time.time()}]
        )
        return {"piece_code": entry["分片编号"], "volume": entry["归档卷"],
                "credential": credential, "status": final_entry["status"], "message": msg}

    # -- 传输血缘关联 --

    def _lineage_for_batch(self, batch_code: str) -> dict[str, Any]:
        """汇总批次血缘：store 中的血缘链路记录加上血缘产物文件，给出当前生效链路号。"""
        lineage_svc = self._safe_import("app.services.transfer_lineage", "TransferLineageService")()
        chains = [r for r in store.rows("transfer_lineage") if r.get("传输批次") == batch_code]
        active = [r for r in chains if r.get("status") == "已生效"]
        files = lineage_svc.query_lineage(batch_code)["lineages"]
        active_code = ""
        if active:
            active_code = active[0].get("链路编号", "")
        elif files:
            active_code = files[0].get("lineage_code", "")
        return {"chains": chains, "files": files, "active_code": active_code}

    def sync_lineage(self, batch_code: str) -> dict[str, Any]:
        """传输血缘关联：把批次生效的血缘链路号补登到尚未关联的恢复范围分片上。"""
        lineage = self._lineage_for_batch(batch_code)
        active_code = lineage["active_code"]
        if not active_code:
            return {"batch_code": batch_code, "linked": 0, "lineage_code": "",
                    "message": "未找到该批次已生效的血缘链路"}
        linked = 0
        for row in store.rows(self.MODULE):
            if row.get("来源批次") == batch_code and not row.get("血缘链路"):
                row["血缘链路"] = active_code
                linked += 1
        self._write_jsonl(
            self._data_dir("events") / "recovery_lineage_log.jsonl",
            [{"action": "sync_lineage", "batch": batch_code,
              "lineage_code": active_code, "linked": linked, "at": time.time()}]
        )
        return {"batch_code": batch_code, "linked": linked, "lineage_code": active_code}

    # -- 看板查询 --

    def _batch_entries(self, batch_code: str) -> list[dict[str, Any]]:
        return [r for r in store.rows(self.MODULE) if r.get("来源批次") == batch_code]

    def coverage_overview(self, batch_code: str) -> list[dict[str, Any]]:
        """覆盖概览：同一批次在各归档卷当前版本下的分片覆盖与缺片情况。"""
        volumes: dict[str, dict[str, Any]] = {}
        for row in self._batch_entries(batch_code):
            if row.get("status") == SUPERSEDED:
                continue
            slot = volumes.setdefault(row["归档卷"], {
                "volume": row["归档卷"],
                "version": row.get("归档版本", ""),
                "verify_state": row.get("卷校验状态", ""),
                "lineage": row.get("血缘链路", ""),
                "total": 0, "recoverable": 0, "missing": 0, "pieces": [],
            })
            slot["total"] += 1
            slot["pieces"].append(row["分片编号"])
            if row.get("status") == RECOVERABLE:
                slot["recoverable"] += 1
            elif row.get("status") == MISSING:
                slot["missing"] += 1
        return list(volumes.values())

    def version_history(self, volume_code: str) -> list[dict[str, Any]]:
        """回查一卷先后用过的全部版本：含已替换的旧版本分片。"""
        history = [
            {
                "id": row.get("id"),
                "归档卷": row.get("归档卷"),
                "归档版本": row.get("归档版本"),
                "来源批次": row.get("来源批次"),
                "分片编号": row.get("分片编号"),
                "成员范围": row.get("成员范围"),
                "校验凭据": row.get("校验凭据"),
                "卷校验状态": row.get("卷校验状态"),
                "status": row.get("status"),
                "登记时间": row.get("登记时间", ""),
            }
            for row in store.rows(self.MODULE)
            if row.get("归档卷") == volume_code
        ]
        history.sort(key=lambda item: (item.get("登记时间") or "", int(item.get("id") or 0)))
        return history

    def replay_history(self, batch_code: str) -> list[dict[str, Any]]:
        """读取重放取片日志：每次重放各片来自哪个卷、采用什么校验凭据。"""
        log_file = self._data_dir("events") / "recovery_replay_log.jsonl"
        return [rec for rec in self._read_jsonl(log_file) if rec.get("batch_code") == batch_code]

    def _last_replay(self, batch_code: str) -> dict[str, Any] | None:
        """汇总上一次重放：重放编号、引用的卷清单与取片数。"""
        records = self.replay_history(batch_code)
        if not records:
            return None
        last_code = records[-1].get("replay_code")
        last = [rec for rec in records if rec.get("replay_code") == last_code]
        return {
            "replay_code": last_code,
            "at": last[-1].get("at"),
            "volumes": sorted({rec.get("volume", "") for rec in last}),
            "pieces": len(last),
            "all_verified": all(rec.get("verified") for rec in last),
        }

    def recovery_board(self, batch_code: str) -> dict[str, Any]:
        """恢复范围看板：覆盖概览 + 可恢复清单 + 缺片记录 + 血缘关联 + 上次重放。

        可恢复清单中每片都带出归档版本、来源批次与校验凭据；
        缺片单独成单；已替换的旧版本分片保留在 superseded 里供回查。
        """
        entries = self._batch_entries(batch_code)
        for entry in entries:
            if entry.get("status") == RECOVERABLE:
                self._materialize_piece(entry)
        return {
            "batch_code": batch_code,
            "coverage": self.coverage_overview(batch_code),
            "recoverable": [e for e in entries if e.get("status") == RECOVERABLE],
            "missing": [e for e in entries if e.get("status") == MISSING],
            "superseded": [e for e in entries if e.get("status") == SUPERSEDED],
            "lineage": self._lineage_for_batch(batch_code),
            "last_replay": self._last_replay(batch_code),
        }

    # -- 历史重放：按经确认的成员范围读取实际数据 --

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        nums = [int(part) for part in "".join(c if c.isdigit() else " " for c in str(version)).split()]
        return tuple(nums) if nums else (0,)

    def _preferred_entries(self, batch_code: str) -> list[dict[str, Any]]:
        """按分片归并可恢复条目：同一片多卷都有时，优先已校验卷，其次较高版本。"""
        recoverable = [e for e in self._batch_entries(batch_code) if e.get("status") == RECOVERABLE]
        by_piece: dict[str, list[dict[str, Any]]] = {}
        for entry in recoverable:
            by_piece.setdefault(entry["分片编号"], []).append(entry)
        chosen = []
        for piece_code, candidates in by_piece.items():
            candidates.sort(
                key=lambda e: (e.get("卷校验状态") == "已校验", self._version_key(e.get("归档版本", ""))),
                reverse=True,
            )
            chosen.append(candidates[0])
        chosen.sort(key=lambda e: parse_member_range(e.get("成员范围", "行1-1"))[0])
        return chosen

    def replay_batch(self, batch_code: str) -> dict[str, Any]:
        """发起重放核对实际数据。

        只读取状态为「可恢复」（经确认的成员范围）的分片实际数据，
        逐片用该片的校验凭据核对内容，并把每片来自哪个卷写进重放取片日志。
        """
        entries = self._preferred_entries(batch_code)
        if not entries:
            return {"error": f"批次 {batch_code} 没有可恢复的分片，无法重放"}

        replay_code = f"RECO-REPLAY-{batch_code}-{int(time.time() * 1000)}"
        fetch_logs = []
        all_records: list[dict[str, Any]] = []
        for entry in entries:
            credential = self._materialize_piece(entry)
            records = self._read_jsonl(self._piece_file(entry["分片编号"]))
            verified = records_checksum(records) == credential.removeprefix("SHA256:")
            all_records.extend(records)
            fetch_logs.append({
                "replay_code": replay_code,
                "batch_code": batch_code,
                "piece_code": entry["分片编号"],
                "member_range": entry.get("成员范围", ""),
                "volume": entry["归档卷"],
                "version": entry.get("归档版本", ""),
                "credential": credential,
                "records": len(records),
                "verified": verified,
                "at": time.time(),
            })

        replay_file = self._data_dir("replay") / f"{replay_code}.jsonl"
        self._write_jsonl(replay_file, all_records)
        self._write_jsonl(self._data_dir("events") / "recovery_replay_log.jsonl", fetch_logs)

        return {
            "replay_code": replay_code,
            "batch_code": batch_code,
            "pieces": fetch_logs,
            "volumes_used": sorted({log["volume"] for log in fetch_logs}),
            "total_records": len(all_records),
            "all_verified": all(log["verified"] for log in fetch_logs),
            "artifact_path": str(replay_file),
        }
