"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import recovery, resource

# 恢复范围看板的固定路径要先于通用 /api/{module} 动态路径注册。
ROUTERS = [recovery, resource]
