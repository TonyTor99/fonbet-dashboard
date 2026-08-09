"""
FastAPI-слой панели fonbet-dashboard.
  GET  /api/sources         — список источников
  GET  /api/source/{key}    — метаданные источника (рынки, лиги, моменты входа, даты)
  POST /api/backtest        — расчёт бэктеста по фильтрам
  POST /api/refresh         — обновить рабочие снимки из боевых БД (sqlite3.backup)
Раздаёт собранный React (frontend/dist) как статику на "/".
"""
import os
import time
import signal
import asyncio
import sqlite3
import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sources import SOURCES
from engine import run_backtest, source_meta, SNAP_DIR
import history

history.init_db()

app = FastAPI(title="Fonbet Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Каталог боевых БД бота (задаётся на сервере). Локально пусто → refresh недоступен.
LIVE_DB_DIR = os.environ.get("LIVE_DB_DIR", "")

# Авто-стоп по простою: гасим панель через N минут без запросов (0 = выключено).
# На сервере включается в systemd (PANEL_IDLE_STOP_MIN), локально по умолчанию выкл.
IDLE_STOP_MIN = int(os.environ.get("PANEL_IDLE_STOP_MIN", "0"))
_last_activity = time.time()


@app.middleware("http")
async def _track_activity(request: Request, call_next):
    global _last_activity
    _last_activity = time.time()
    return await call_next(request)


@app.on_event("startup")
async def _idle_watchdog():
    if IDLE_STOP_MIN <= 0:
        return

    async def _watch():
        while True:
            await asyncio.sleep(60)
            if time.time() - _last_activity > IDLE_STOP_MIN * 60:
                print(f"[idle] Простой >{IDLE_STOP_MIN} мин — останавливаю панель.")
                os.kill(os.getpid(), signal.SIGTERM)
                return

    asyncio.create_task(_watch())


@app.get("/api/sources")
def list_sources():
    return [{"key": k, "label": v["label"], "kind": v["kind"]}
            for k, v in SOURCES.items()]


@app.get("/api/source/{key}")
def get_source(key: str):
    if key not in SOURCES:
        raise HTTPException(404, "Неизвестный источник")
    return source_meta(key)


@app.post("/api/backtest")
def backtest(params: dict):
    try:
        return run_backtest(params)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/history/{source}")
def hist_list(source: str):
    return history.list_entries(source)


@app.post("/api/history/{source}")
def hist_add(source: str, payload: dict):
    return history.add(source, payload.get("form"), payload.get("params"),
                       payload.get("summary"))


@app.delete("/api/history/{source}/{entry_id}")
def hist_delete(source: str, entry_id: int):
    history.delete(source, entry_id)
    return {"ok": True}


@app.delete("/api/history/{source}")
def hist_clear(source: str):
    history.clear(source)
    return {"ok": True}


@app.post("/api/refresh")
def refresh():
    """Делает sqlite3.backup каждой боевой БД в рабочую папку snapshots."""
    if not LIVE_DB_DIR or not os.path.isdir(LIVE_DB_DIR):
        raise HTTPException(400, "Боевые БД недоступны (LIVE_DB_DIR не задан) — "
                                 "локальный режим, работаем на снимках.")
    done, errors = [], []
    for src in SOURCES.values():
        db = src["db"]
        live = os.path.join(LIVE_DB_DIR, db)
        dest = os.path.join(SNAP_DIR, db)
        if not os.path.exists(live):
            errors.append(f"{db}: нет на сервере")
            continue
        try:
            s = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
            d = sqlite3.connect(dest)
            s.backup(d)
            d.close(); s.close()
            done.append(db)
        except Exception as e:
            errors.append(f"{db}: {e}")
    return {"updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated": done, "errors": errors}


@app.get("/api/status")
def status():
    """Время последнего обновления снимков (mtime самого свежего файла)."""
    latest = None
    for src in SOURCES.values():
        path = os.path.join(SNAP_DIR, src["db"])
        if os.path.exists(path):
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            latest = mt if latest is None or mt > latest else latest
    return {"snapshots_updated": latest.strftime("%Y-%m-%d %H:%M:%S") if latest else None,
            "live_available": bool(LIVE_DB_DIR and os.path.isdir(LIVE_DB_DIR))}


# --- Раздача фронта (React без сборки: index.html + vendor + css) ------------
FRONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(FRONT):
    app.mount("/vendor", StaticFiles(directory=os.path.join(FRONT, "vendor")), name="vendor")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONT, "index.html"))

    @app.get("/app.css")
    def appcss():
        return FileResponse(os.path.join(FRONT, "app.css"))
