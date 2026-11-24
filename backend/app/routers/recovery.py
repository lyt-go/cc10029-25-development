"""恢复范围看板接口：按批次查询可恢复范围、覆盖概览、版本回查与重放核对。

这些路径挂在 /api/recovery_scope/ 下，与通用资源路由 /api/{module} 互补：
通用路由负责恢复范围条目的列表/登记/动作，这里负责跨卷聚合的看板视图。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import service_for
from app.services.recovery_scope import RecoveryScopeService

router = APIRouter(prefix="/api/recovery_scope", tags=["恢复范围看板"])


def _service() -> RecoveryScopeService:
    service = service_for("recovery_scope")
    if not isinstance(service, RecoveryScopeService):
        raise HTTPException(status_code=404, detail="恢复范围看板服务未注册")
    return service


class PublishPayload(BaseModel):
    volume_code: str
    batch_code: str
    version: str
    piece_count: int = Field(default=3, ge=1, le=50)
    missing: list[int] = Field(default_factory=list)
    verified: bool = False
    lineage_code: str = ""


class BatchPayload(BaseModel):
    batch_code: str


class RestorePayload(BaseModel):
    entry_id: int


@router.get("/dashboard", response_model=dict)
def dashboard(batch_code: str = Query(..., min_length=1)) -> dict[str, Any]:
    """按批次查询恢复范围看板：覆盖概览、可恢复清单、缺片记录、血缘与上次重放。"""
    return _service().recovery_board(batch_code.strip())


@router.post("/publish", response_model=dict)
def publish_volume(payload: PublishPayload) -> dict[str, Any]:
    """发布归档卷版本：旧版本分片标记替换但仍可回查，新版本分片登记入清单。"""
    return _service().publish_volume(
        payload.volume_code, payload.batch_code, payload.version,
        piece_count=payload.piece_count, missing=payload.missing,
        verified=payload.verified, lineage_code=payload.lineage_code,
    )


@router.post("/restore", response_model=dict)
def restore_piece(payload: RestorePayload) -> dict[str, Any]:
    """补回缺片：重新物化分片数据、刷新校验凭据并置为可恢复。"""
    result = _service().restore_piece(payload.entry_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/replay", response_model=dict)
def replay_batch(payload: BatchPayload) -> dict[str, Any]:
    """发起重放：按经确认的成员范围读取实际数据，记下每片来自哪个卷。"""
    result = _service().replay_batch(payload.batch_code.strip())
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/sync_lineage", response_model=dict)
def sync_lineage(payload: BatchPayload) -> dict[str, Any]:
    """传输血缘关联：把批次生效的血缘链路号补登到未关联的恢复范围分片。"""
    return _service().sync_lineage(payload.batch_code.strip())


@router.get("/versions", response_model=dict)
def version_history(volume_code: str = Query(..., min_length=1)) -> dict[str, Any]:
    """回查一卷先后用过的全部版本，含已替换的旧版本分片。"""
    items = _service().version_history(volume_code.strip())
    return {"volume_code": volume_code, "items": items, "total": len(items)}


@router.get("/replays", response_model=dict)
def replay_history(batch_code: str = Query(..., min_length=1)) -> dict[str, Any]:
    """查询批次的重放取片记录：每次重放各片来自哪个卷、采用什么校验凭据。"""
    items = _service().replay_history(batch_code.strip())
    return {"batch_code": batch_code, "items": items, "total": len(items)}
