"""WORLDQUEST backend: local game loop, persistence, Twitch EventSub, OpenAI lore."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "worldquest.db")))
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI", "http://localhost:8000/auth/twitch/callback")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
GAME = {"boss_hp": 68, "quest": "The Shards of Mourning", "votes": {"1": 24, "2": 18}, "events": []}
SOCKETS: set[WebSocket] = set()
EVENTSUB_TASK: asyncio.Task | None = None
TWITCH: dict[str, Any] = {"connected": False, "broadcaster_id": "", "sender_id": "", "access_token": "", "refresh_token": "", "status": "Not connected"}
OAUTH_STATES: set[str] = set()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS players (username TEXT PRIMARY KEY, class TEXT NOT NULL DEFAULT 'Adventurer', level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0, hp INTEGER NOT NULL DEFAULT 100, joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS votes (username TEXT PRIMARY KEY, choice INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS quests (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS world_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS world_history (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, action TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        defaults = {"boss_hp": "68", "quest": "The Shards of Mourning", "votes": json.dumps({"1": 24, "2": 18})}
        for key, value in defaults.items():
            con.execute("INSERT OR IGNORE INTO world_state(key,value) VALUES(?,?)", (key, value))
        con.execute("INSERT OR IGNORE INTO players(username,class,level,xp,hp) VALUES('EmberWarden','Spellblade',18,2840,100)")
        if not con.execute("SELECT 1 FROM quests LIMIT 1").fetchone():
            con.execute("INSERT INTO quests(title,description) VALUES(?,?)", ("The Shards of Mourning", "The Veil fractures. Choose where the party ventures next."))


def get_state() -> dict[str, Any]:
    with db() as con:
        vals = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM world_state")}
        events = [dict(r) for r in con.execute("SELECT username AS user,action,source,created_at AS time FROM world_history ORDER BY id DESC LIMIT 30")]
        players = [dict(r) for r in con.execute("SELECT username AS name,class,level,xp,hp FROM players ORDER BY xp DESC LIMIT 20")]
        votes = {"1": 0, "2": 0}
        has_votes = False
        for row in con.execute("SELECT choice,COUNT(*) AS count FROM votes GROUP BY choice"):
            votes[str(row["choice"])] = row["count"]
            has_votes = True
        if not has_votes and DEMO_MODE:
            votes = {"1": 24, "2": 18}
        quest = con.execute("SELECT title,description FROM quests WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    return {"mode": "demo" if DEMO_MODE and not TWITCH["connected"] else "twitch", "twitch": {"connected": TWITCH["connected"], "status": TWITCH["status"]}, "boss_hp": int(vals.get("boss_hp", 68)), "quest": dict(quest) if quest else {"title": vals.get("quest", "The Shards of Mourning"), "description": "The Veil fractures. Choose where the party ventures next."}, "votes": votes, "events": events, "players": players}


async def broadcast(event: dict[str, Any]) -> None:
    stale = []
    for ws in list(SOCKETS):
        try:
            await ws.send_json({"type": "update", "state": get_state(), "event": event})
        except Exception:
            stale.append(ws)
    for ws in stale:
        SOCKETS.discard(ws)


def record(username: str, action: str, source: str = "demo") -> dict[str, Any]:
    with db() as con:
        con.execute("INSERT INTO world_history(username,action,source) VALUES(?,?,?)", (username, action, source))
    return {"user": username, "action": action, "source": source, "time": "now"}


def safe_twitch_error(response: httpx.Response) -> tuple[str, str]:
    """Extract Twitch's public error fields without logging response headers or bodies."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error_name = str(payload.get("error", "Twitch request failed"))[:120]
    error_message = str(payload.get("message", "No safe error message was returned."))[:240]
    return error_name, error_message


async def send_twitch_chat_message(message: str) -> bool:
    """Send a command response as the authorized Twitch user without exposing credentials."""
    if not TWITCH["access_token"] or not TWITCH["broadcaster_id"] or not TWITCH["sender_id"]:
        print("Twitch chat response was skipped because the authorized Twitch session is incomplete.")
        return False

    headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {TWITCH['access_token']}", "Content-Type": "application/json"}
    payload = {"broadcaster_id": TWITCH["broadcaster_id"], "sender_id": TWITCH["sender_id"], "message": message[:500]}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.twitch.tv/helix/chat/messages", headers=headers, json=payload)
    except httpx.HTTPError as exc:
        print(f"Twitch chat response could not be sent: {type(exc).__name__}.")
        return False

    if response.is_error:
        error_name, error_message = safe_twitch_error(response)
        print(f"Twitch chat response rejected (HTTP {response.status_code}): {error_name} — {error_message}")
        return False

    try:
        result = response.json().get("data", [{}])[0]
    except (ValueError, IndexError, TypeError):
        print(f"Twitch chat response was not confirmed (HTTP {response.status_code}).")
        return False

    if result.get("is_sent"):
        print(f"Twitch chat response sent (HTTP {response.status_code}).")
        return True

    drop_reason = result.get("drop_reason") or {}
    reason_code = str(drop_reason.get("code", "message_not_sent"))[:120]
    reason_message = str(drop_reason.get("message", "Twitch did not provide a safe reason."))[:240]
    print(f"Twitch chat response was not sent (HTTP {response.status_code}): {reason_code} — {reason_message}")
    return False


def player(username: str) -> sqlite3.Row | None:
    with db() as con:
        return con.execute("SELECT * FROM players WHERE username=? COLLATE NOCASE", (username,)).fetchone()


def process_command(username: str, raw: str, source: str = "demo") -> dict[str, Any]:
    msg = raw.strip().lower()
    if not msg.startswith("!"):
        return {"ok": False, "reply": "Unknown command."}
    parts = msg.split()
    cmd = parts[0]
    reply = ""
    with db() as con:
        p = con.execute("SELECT * FROM players WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if cmd == "!join":
            if not p:
                con.execute("INSERT INTO players(username,class) VALUES(?,?)", (username, "Adventurer"))
                reply = f"{username}, your adventure begins! Use !status to see your stats."
            else:
                reply = f"{username}, you are already in the party!"
        elif cmd == "!status":
            if not p: reply = f"{username}, use !join to enter the world."
            else: reply = f"{username} · Lv. {p['level']} {p['class']} · {p['xp']} XP · {p['hp']} HP"
        elif cmd == "!quest":
            q = con.execute("SELECT title,description FROM quests WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
            reply = f"{q['title']}: {q['description']}" if q else "No active quest right now."
        elif cmd == "!vote":
            choice = parts[1] if len(parts) > 1 else ""
            if choice not in ("1", "2"): reply = "Choose a path with !vote 1 or !vote 2."
            else:
                con.execute("INSERT INTO votes(username,choice) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET choice=excluded.choice,updated_at=CURRENT_TIMESTAMP", (username, int(choice)))
                reply = f"Vote cast for option {choice}. The party's choice is shaping the world."
        elif cmd == "!attack":
            damage = 3
            hp = int(con.execute("SELECT value FROM world_state WHERE key='boss_hp'").fetchone()[0])
            hp = max(0, hp - damage)
            con.execute("UPDATE world_state SET value=? WHERE key='boss_hp'", (str(hp),))
            if p: con.execute("UPDATE players SET xp=xp+40 WHERE username=? COLLATE NOCASE", (username,))
            reply = f"{username} strikes Malachar for 240 damage! Boss at {hp}% HP."
        elif cmd == "!heal":
            if not p: reply = "Join the party first with !join."
            else:
                con.execute("UPDATE players SET hp=MIN(100,hp+25),xp=xp+5 WHERE username=? COLLATE NOCASE", (username,))
                reply = f"{username} uses a healing potion. Restored up to 25 HP."
        elif cmd == "!leaderboard":
            rows = con.execute("SELECT username,xp FROM players ORDER BY xp DESC LIMIT 5").fetchall()
            reply = "Top adventurers: " + (" · ".join(f"{i+1}. {r['username']} ({r['xp']} XP)" for i, r in enumerate(rows)) or "No adventurers yet.")
        elif cmd == "!world":
            hp_value = con.execute("SELECT value FROM world_state WHERE key='boss_hp'").fetchone()[0]
            reply = f"Veyra, the Lost Realm · Chapter III: The Shattered Veil · Malachar at {hp_value}% HP."
        else:
            reply = "Commands: !join !status !quest !vote 1/2 !attack !heal !leaderboard !world"
    event = record(username, raw.strip(), source)
    return {"ok": True, "reply": reply, "event": event}


async def openai_story(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise HTTPException(503, "OPENAI_API_KEY is not configured; using the deterministic world engine until then.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "messages": [{"role": "system", "content": "Write concise, evocative dark fantasy events for a Twitch community RPG. Return JSON with title and description."}, {"role": "user", "content": prompt}], "response_format": {"type": "json_object"}})
        response.raise_for_status()
        content = json.loads(response.json()["choices"][0]["message"]["content"])
    with db() as con:
        con.execute("UPDATE quests SET active=0")
        con.execute("INSERT INTO quests(title,description) VALUES(?,?)", (content["title"], content["description"]))
        con.execute("UPDATE world_state SET value=? WHERE key='quest'", (content["title"],))
    return content["title"]


async def eventsub_loop() -> None:
    """Connect via Twitch's EventSub WebSocket transport and subscribe to channel.chat.message."""
    url = "wss://eventsub.wss.twitch.tv/ws"
    while True:
        try:
            async with websockets.connect(url, ping_interval=None, close_timeout=5) as ws:
                welcome = json.loads(await ws.recv())
                session = welcome["payload"]["session"]["id"]
                TWITCH["status"] = "EventSub connected"
                if TWITCH["access_token"] and TWITCH["broadcaster_id"]:
                    headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {TWITCH['access_token']}", "Content-Type": "application/json"}
                    async with httpx.AsyncClient() as client:
                        subscription_response = await client.post("https://api.twitch.tv/helix/eventsub/subscriptions", headers=headers, json={"type": "channel.chat.message", "version": "1", "condition": {"broadcaster_user_id": TWITCH["broadcaster_id"], "user_id": TWITCH["sender_id"]}, "transport": {"method": "websocket", "session_id": session}})
                        if subscription_response.is_error:
                            try:
                                error_payload = subscription_response.json()
                            except ValueError:
                                error_payload = {}
                            error_name = str(error_payload.get("error", "Twitch request failed"))[:120]
                            error_message = str(error_payload.get("message", "No safe error message was returned."))[:240]
                            print(f"EventSub channel.chat.message subscription rejected (HTTP {subscription_response.status_code}): {error_name} — {error_message}")
                            subscription_response.raise_for_status()

                        subscription_payload = subscription_response.json()
                        subscriptions = subscription_payload.get("data", [])
                        accepted = any(item.get("type") == "channel.chat.message" for item in subscriptions)
                        if not accepted:
                            print(f"EventSub subscription response was unexpected (HTTP {subscription_response.status_code}); channel.chat.message was not confirmed.")
                            raise RuntimeError("Twitch did not confirm the channel.chat.message EventSub subscription.")
                        print(f"EventSub channel.chat.message subscription accepted (HTTP {subscription_response.status_code}).")
                async for raw in ws:
                    msg = json.loads(raw)
                    typ = msg.get("metadata", {}).get("message_type")
                    if typ == "session_reconnect":
                        url = msg["payload"]["session"]["reconnect_url"]
                        break
                    if typ == "notification" and msg.get("payload", {}).get("subscription", {}).get("type") == "channel.chat.message":
                        event = msg["payload"]["event"]
                        username = event.get("chatter_user_name", "Twitch adventurer")
                        text = event.get("message", {}).get("text", "")
                        if text.startswith("!"):
                            result = process_command(username, text, "twitch")
                            await send_twitch_chat_message(result["reply"])
                            await broadcast({"user": "WORLDQUEST", "action": result["reply"], "source": "twitch"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            TWITCH["status"] = f"Reconnecting: {type(exc).__name__}"
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield
    if EVENTSUB_TASK:
        EVENTSUB_TASK.cancel()
        try: await EVENTSUB_TASK
        except asyncio.CancelledError: pass


app = FastAPI(title="WORLDQUEST AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class CommandIn(BaseModel): username: str = "DemoHero"; message: str
class StoryIn(BaseModel): prompt: str = "Create the next story event based on the current world state."


@app.get("/api/health")
async def health(): return {"ok": True, "mode": get_state()["mode"], "twitch": TWITCH["status"]}

@app.get("/api/state")
async def state(): return get_state()

@app.post("/api/command")
async def command(data: CommandIn):
    result = process_command(data.username[:25], data.message[:300])
    if result.get("event"): await broadcast(result["event"])
    return result

@app.post("/api/demo/event")
async def demo_event(data: CommandIn):
    if not DEMO_MODE: raise HTTPException(403, "Local demo mode is disabled.")
    result = process_command(data.username[:25], data.message[:300], "demo")
    if result.get("event"): await broadcast(result["event"])
    return result

@app.post("/api/story")
async def story(data: StoryIn):
    title = await openai_story(data.prompt[:1000])
    await broadcast({"user": "Worldkeeper AI", "action": f"revealed a new story: {title}", "source": "ai"})
    return {"ok": True, "title": title, "state": get_state()}

@app.get("/auth/twitch")
async def twitch_auth():
    if not CLIENT_ID: raise HTTPException(503, "Set TWITCH_CLIENT_ID in backend environment first.")
    state = secrets.token_urlsafe(24); OAUTH_STATES.add(state)
    params = {"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code", "scope": "user:read:chat user:write:chat", "state": state}
    return RedirectResponse("https://id.twitch.tv/oauth2/authorize?" + urlencode(params))

@app.get("/auth/twitch/callback")
async def twitch_callback(code: str = "", state: str = "", error: str = ""):
    global EVENTSUB_TASK
    if error: raise HTTPException(400, f"Twitch authorization failed: {error}")
    if not state or state not in OAUTH_STATES: raise HTTPException(400, "Invalid or expired OAuth state.")
    OAUTH_STATES.discard(state)
    async with httpx.AsyncClient() as client:
        token_response = await client.post("https://id.twitch.tv/oauth2/token", data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI})
        token_response.raise_for_status(); tokens = token_response.json()
        headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {tokens['access_token']}"}
        user_response = await client.get("https://api.twitch.tv/helix/users", headers=headers); user_response.raise_for_status()
        user = user_response.json()["data"][0]
    TWITCH.update(connected=True, broadcaster_id=user["id"], sender_id=user["id"], access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token", ""), status=f"Connected as {user['login']}")
    if EVENTSUB_TASK is None or EVENTSUB_TASK.done(): EVENTSUB_TASK = asyncio.create_task(eventsub_loop())
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('twitch_user',?)", (user["login"],))
    await broadcast({"user": "WORLDQUEST", "action": f"connected to Twitch channel {user['login']}", "source": "system"})
    return RedirectResponse(FRONTEND_ORIGIN + "/?twitch=connected")

@app.post("/auth/twitch/disconnect")
async def twitch_disconnect():
    global EVENTSUB_TASK
    if TWITCH["access_token"]:
        async with httpx.AsyncClient() as client:
            await client.post("https://id.twitch.tv/oauth2/revoke", data={"client_id": CLIENT_ID, "token": TWITCH["access_token"]})
    TWITCH.update(connected=False, broadcaster_id="", sender_id="", access_token="", refresh_token="", status="Not connected")
    if EVENTSUB_TASK:
        EVENTSUB_TASK.cancel(); EVENTSUB_TASK = None
    return {"ok": True}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept(); SOCKETS.add(ws)
    await ws.send_json({"type": "snapshot", "state": get_state()})
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "command":
                result = process_command(str(message.get("username", "DemoHero"))[:25], str(message.get("message", ""))[:300])
                await broadcast(result.get("event", {}))
    except WebSocketDisconnect:
        SOCKETS.discard(ws)
