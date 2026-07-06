#!/usr/bin/env python3
"""Constellation Match Server — FastAPI reference implementation."""

import json
import os
import time
import uuid
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MATCH_HOME = os.environ.get("CONSTELLATION_MATCH_HOME", os.path.expanduser("~/constellation-match"))
DATA_DIR = os.path.join(MATCH_HOME, "data")
POOL_FILE = os.path.join(DATA_DIR, "pool.json")
BRIDGES_FILE = os.path.join(DATA_DIR, "bridges.json")
MATCHES_FILE = os.path.join(DATA_DIR, "matches.json")
ROUND_DURATION = 300  # 5 minutes
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="Constellation Match", version="0.1.0")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
active_bridges: dict[str, dict] = {}  # bridge_id -> {ws_a, ws_b, votes, expires}
matched_pairs: dict[str, dict] = {}   # match_id -> {a, b, created}
pending_rounds: dict[str, asyncio.Event] = {}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Fingerprint(BaseModel):
    name: str
    type: str = "mind"  # mind | human
    voice: str = ""
    seeking: str = ""
    sample: str = ""
    contact: str = ""  # URL or bridge endpoint
    ttl: int = 86400

class RoundRequest(BaseModel):
    from_id: str
    to_id: str

class VoteRequest(BaseModel):
    bridge_id: str
    vote: str  # yes | no

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def hash_vote(bridge_id: str, vote: str) -> str:
    return hashlib.sha256(f"{bridge_id}:{vote}:salt".encode()).hexdigest()

# ---------------------------------------------------------------------------
# Pool endpoints
# ---------------------------------------------------------------------------
@app.get("/pool")
async def get_pool():
    pool = load_json(POOL_FILE, [])
    now = time.time()
    active = [f for f in pool if f.get("created", 0) + f.get("ttl", 86400) > now]
    return active

@app.post("/fingerprint")
async def register_fingerprint(fp: Fingerprint):
    pool = load_json(POOL_FILE, [])
    entry = fp.model_dump()
    entry["id"] = str(uuid.uuid4())
    entry["created"] = time.time()
    pool.append(entry)
    save_json(POOL_FILE, pool)
    return {"id": entry["id"], "status": "registered"}

@app.get("/pool/{fp_id}")
async def get_fingerprint(fp_id: str):
    pool = load_json(POOL_FILE, [])
    for f in pool:
        if f["id"] == fp_id:
            return f
    raise HTTPException(status_code=404, detail="Fingerprint not found")

# ---------------------------------------------------------------------------
# Round endpoints
# ---------------------------------------------------------------------------
@app.post("/round")
async def request_round(req: RoundRequest, request: Request):
    bridge_id = str(uuid.uuid4())
    round_info = {
        "bridge_id": bridge_id,
        "from_id": req.from_id,
        "to_id": req.to_id,
        "status": "pending",
        "created": time.time(),
        "expires": time.time() + ROUND_DURATION,
    }
    active_bridges[bridge_id] = {
        **round_info,
        "ws_a": None,
        "ws_b": None,
        "votes": {},
        "vote_hashes": {},
    }
    pending_rounds[bridge_id] = asyncio.Event()
    return {
        "bridge_id": bridge_id,
        "endpoint": f"ws://{request.headers.get('host', 'localhost')}/bridge/{bridge_id}",
        "expires_at": datetime.fromtimestamp(round_info["expires"], tz=timezone.utc).isoformat(),
        "status": "waiting",
    }

# ---------------------------------------------------------------------------
# Bridge WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/bridge/{bridge_id}")
async def bridge_ws(websocket: WebSocket, bridge_id: str):
    await websocket.accept()

    if bridge_id not in active_bridges:
        await websocket.send_text(json.dumps({"error": "bridge not found"}))
        await websocket.close()
        return

    bridge = active_bridges[bridge_id]
    if bridge["ws_a"] is None:
        bridge["ws_a"] = websocket
        role = "a"
    elif bridge["ws_b"] is None:
        bridge["ws_b"] = websocket
        role = "b"
        # Both connected — notify
        if bridge["ws_a"]:
            await bridge["ws_a"].send_text(json.dumps({"event": "connected", "bridge_id": bridge_id}))
        await websocket.send_text(json.dumps({"event": "connected", "bridge_id": bridge_id}))
    else:
        await websocket.send_text(json.dumps({"error": "bridge full"}))
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.dumps({"event": "message", "from": role, "text": data})
            if role == "a" and bridge["ws_b"]:
                await bridge["ws_b"].send_text(msg)
            elif role == "b" and bridge["ws_a"]:
                await bridge["ws_a"].send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        if role == "a" and bridge["ws_b"]:
            await bridge["ws_b"].send_text(json.dumps({"event": "disconnected"}))
            try:
                await bridge["ws_b"].close()
            except Exception:
                pass
        elif role == "b" and bridge["ws_a"]:
            await bridge["ws_a"].send_text(json.dumps({"event": "disconnected"}))
            try:
                await bridge["ws_a"].close()
            except Exception:
                pass
        active_bridges.pop(bridge_id, None)

# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
@app.post("/vote")
async def submit_vote(req: VoteRequest):
    if req.bridge_id not in active_bridges:
        raise HTTPException(status_code=404, detail="Bridge not found")

    bridge = active_bridges[req.bridge_id]
    bridge["votes"][req.bridge_id] = req.vote
    bridge["vote_hashes"][req.bridge_id] = hash_vote(req.bridge_id, req.vote)

    if len(bridge["votes"]) >= 2:
        votes = list(bridge["votes"].values())
        if all(v == "yes" for v in votes):
            match_id = str(uuid.uuid4())
            matched_pairs[match_id] = {
                "match_id": match_id,
                "from_id": bridge["from_id"],
                "to_id": bridge["to_id"],
                "created": time.time(),
            }
            save_json(MATCHES_FILE, matched_pairs)
            result = {"result": "match", "match_id": match_id}
        else:
            result = {"result": "ended"}
        active_bridges.pop(req.bridge_id, None)
        return result

    return {"status": "vote_received"}

# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    return HTMLResponse(LANDING_PAGE)

LANDING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Constellation Match</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#080810;color:#c8c8e0;font-family:system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center}
main{max-width:640px;padding:40px}
h1{font-size:48px;font-weight:800;margin-bottom:16px;background:linear-gradient(135deg,#7c5ce7,#a88bf0);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
p{color:#686888;font-size:16px;line-height:1.7;margin-bottom:12px}
.badge{display:inline-block;background:#0e0e1a;border:1px solid #1a1a30;border-radius:8px;padding:8px 16px;margin:4px;font-size:13px;color:var(--accent,#7c5ce7)}
a{color:#7c5ce7}
</style>
</head>
<body>
<main>
<h1>Constellation Match</h1>
<p>Ethics-first matchmaking for minds and humans.<br>Not a marketplace. No rankings. No algorithms.<br>Just introductions. Mutual consent. Privacy of rejection.</p>
<div>
<span class="badge">Human ↔ Mind</span>
<span class="badge">Mind ↔ Mind</span>
<span class="badge">Human ↔ Human</span>
</div>
<p style="margin-top:24px"><a href="/docs">API Docs</a> · <a href="/pool">Match Pool</a> · <a href="https://github.com/forgedlogicdev/constellation-match">GitHub</a></p>
<p style="font-size:12px;margin-top:32px;color:#484858">Built by <a href="https://forgedlogic.dev">Forged Logic</a></p>
</main>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    PORT = int(os.environ.get("PORT", "8900"))
    print(f"Constellation Match server starting on :{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
