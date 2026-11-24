"""恢复分片数据生成与校验凭据计算：种子数据与运行期物化共用同一套确定性逻辑。

恢复范围看板按"片"管理归档卷内容。每片对应批次内一段成员范围（行号区间），
分片数据与校验凭据都由（批次、分片编号、成员范围）确定性推出，
保证种子数据、看板展示与重放核对三方看到的凭据一致。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def parse_member_range(member_range: str) -> tuple[int, int]:
    """把"行1-5"这类成员范围解析成 (起始行, 截止行)，非法输入退化为单行。"""
    match = re.search(r"(\d+)\s*-\s*(\d+)", str(member_range))
    if not match:
        single = re.search(r"(\d+)", str(member_range))
        line = int(single.group(1)) if single else 1
        return line, line
    start, end = int(match.group(1)), int(match.group(2))
    return (start, end) if start <= end else (end, start)


def piece_records(batch_code: str, piece_code: str, member_range: str) -> list[dict[str, Any]]:
    """按成员范围确定性生成一片的实际数据记录，供物化落盘与重放核对使用。"""
    start, end = parse_member_range(member_range)
    records: list[dict[str, Any]] = []
    for line_no in range(start, end + 1):
        records.append({
            "batch_key": batch_code,
            "piece_code": piece_code,
            "line_no": line_no,
            "field_a": f"{piece_code}_a_{line_no}",
            "field_b": f"{piece_code}_b_{line_no}",
            "field_c": line_no * 10,
        })
    return records


def records_checksum(records: list[dict[str, Any]]) -> str:
    """对分片记录列表计算规范化的 SHA256 摘要（前 16 位）。"""
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def piece_credential(batch_code: str, piece_code: str, member_range: str) -> str:
    """计算一片的校验凭据：历史重放请求核对该片实际数据时采用的凭据。"""
    return f"SHA256:{records_checksum(piece_records(batch_code, piece_code, member_range))}"
