# -*- coding: utf-8 -*-
"""
system.py — Router aggregator.

The original monolithic system.py (700+ lines, 30+ endpoints) has been split
into four focused modules. This file re-exports a single `router` that
includes all sub-routers so main.py requires no changes.

Sub-modules:
  admin_tools  — TD audit/fix, shadow cleanup, tax policy, billing sync
  maintenance  — backup, restore, import, audit logs, retention, restart
  health       — health probes, metrics, stats, worker status, version
  compute      — payment computation, global search, undo, WebSocket
"""

from fastapi import APIRouter

from backend.routes.admin_tools import router as _admin_tools_router
from backend.routes.maintenance import router as _maintenance_router
from backend.routes.health import router as _health_router
from backend.routes.compute import router as _compute_router

# Single aggregated router — registered in main.py as app.include_router(system.router)
router = APIRouter()

router.include_router(_admin_tools_router)
router.include_router(_maintenance_router)
router.include_router(_health_router)
router.include_router(_compute_router)
