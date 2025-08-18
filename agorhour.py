#!/usr/bin/env python3
"""
Single-file MVP: FastAPI backend + minimal PWA frontend + hourly AI + Supabase
Run: python agorhour.py
Needs .env with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY at minimum.
"""

import importlib
import subprocess
import sys
import os
import json
import re
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, Tuple

# -- Auto-install missing dependencies --

def need(pkg, import_name=None):
    try:
        importlib.import_module(import_name or pkg)
        return False
    except ImportError:
        return True

def pip_install(*pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", *pkgs])

missing = []
if need("fastapi"): missing += ["fastapi"]
if need("uvicorn"): missing += ["uvicorn"]
if need("python-dotenv", "dotenv"): missing += ["python-dotenv"]
if need("apscheduler"): missing += ["apscheduler"]
if need("supabase"): missing += ["supabase"]
if need("psycopg2"): missing += ["psycopg2-binary"]
if need("openai"): missing += ["openai"]
if missing:
    pip_install(*missing)

# -- Imports --

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import psycopg2
from supabase import create_client, Client
from openai import OpenAI

# -- Config / Env --

load_dotenv()
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
TZ = os.getenv("TZ", "Europe/Rome")
TZINFO = ZoneInfo(TZ)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")  # optional, for DDL
AGORHOUR_CRON_SECRET = os.getenv("AGORHOUR_CRON_SECRET", "change-me")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in env.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
ai_client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# -- Schema (per brief) --

DDL_SQL = """
create extension if not exists pgcrypto;

create table if not exists hour_questions (
    id uuid primary key default gen_random_uuid(),
    hour_key text unique not null,
    text varchar(140) not null,
    created_at timestamptz default now(),
    expires_at timestamptz not null,
    open_mode boolean default true
);

create table if not exists anon_sessions (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz default now(),
    avatar_seed int not null
);

create table if not exists answers (
    id uuid primary key default gen_random_uuid(),
    hour_id uuid references hour_questions(id) on delete cascade,
    session_id uuid references anon_sessions(id) on delete cascade,
    stance varchar(8) check (stance in ('AGREE','DISAGREE')) null,
    text varchar(120) not null,
    exposed boolean default false,
    created_at timestamptz default now()
);

create table if not exists reactions (
    id uuid primary key default gen_random_uuid(),
    answer_id uuid references answers(id) on delete cascade,
    session_id uuid references anon_sessions(id) on delete cascade,
    kind varchar(8) check (kind in ('LIKE','UNLIKE')),
    created_at timestamptz default now(),
    unique (answer_id, session_id)
);

-- Helpful indexes
create index if not exists idx_hour_questions_hour_key on hour_questions(hour_key);
create index if not exists idx_answers_hour on answers(hour_id);
create index if not exists idx_reactions_answer on reactions(answer_id);
"""

def run_ddl_if_possible():
    if not SUPABASE_DB_URL:
        print("INFO: SUPABASE_DB_URL not set → skipping DDL (assume tables exist).")
        return
    conn = psycopg2.connect(SUPABASE_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(DDL_SQL)
    conn.close()
    print("DDL executed OK.")

run_ddl_if_possible()

# -- Helpers --

def now_tz() -> datetime:
    return datetime.now(tz=TZINFO)

def hour_key_for(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H")  # canonical in UTC

def hour_window(dt: datetime) -> Tuple[datetime, datetime]:
    start = dt.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return start, end

def end_of_hour(dt: datetime) -> datetime:
    _, end = hour_window(dt)
    return end

def score_for_answer(answer_id: str) -> int:
    likes = supabase.table("reactions").select("id").eq("answer_id", answer_id).eq("kind","LIKE").execute().data
    unlikes = supabase.table("reactions").select("id").eq("answer_id", answer_id).eq("kind","UNLIKE").execute().data
    return (len(likes or [])) - (len(unlikes or []))

EMOJI_POOL = [
    "😶","🫥","🫣","🫡","😏","😐","🙃","😎","🥸","🤖",
    "👻","👽","🐸","🦊","🐼","🐨","🦉","🐺","🦄","🐙"
]

def avatar_from_seed(seed: int) -> Dict[str, Any]:
    hue = seed % 360
    emoji = EMOJI_POOL[seed % len(EMOJI_POOL)]
    return {"hsl": f"hsl({hue} 70% 50%)", "emoji": emoji}

# -- Working Meter (server-side mirror of client logic) --

HARD_RED_PATTERNS = [
    r"\b(kill|murder|rape|lynch|gas|exterminate)\b",
    r"\b(doxx|address|phone|ssn)\b",
    r"\b(slur1|slur2|slur3)\b"  # placeholder: keep policy list server-side
]
MILD_YELLOW_PATTERNS = [
    r"[A-Z]{5,}",
    r"[!?.]{3,}",
    r"\b(damn|hell|crap)\b",
]

def meter_color(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return "red"
    for p in HARD_RED_PATTERNS:
        if re.search(p, t):
            return "red"
    for p in MILD_YELLOW_PATTERNS:
        if re.search(p, t):
            return "yellow"
    if len(text or "") > 110:
        return "yellow"
    return "green"

# -- AI Question Generator --

SYSTEM_PROMPT = (
    "You are AgorHour's Question Master. Generate ONE concise, open-ended debate question.\n"
    "Rules:\n"
    "- Max 120 characters.\n"
    "- Plain English, neutral→mildly provocative.\n"
    "- Safe-for-work; no NSFW/hate/personal data.\n"
    "- Rotate themes: life, love, food, work, ethics, society, culture, politics (soft), tech, future.\n"
    "- Output ONLY the question."
)
THEMES = ["life","love","food","work","ethics","society","culture","politics","tech","future"]

def ai_generate_question(last_headline: str, next_theme: str) -> str:
    if not ai_client:
        stock = {
            "life":"Is happiness more comfort or challenge?",
            "love":"Can long-distance love really last?",
            "food":"Is fast food killing tradition or saving time?",
            "work":"Should employers track digital productivity?",
            "ethics":"Is lying ever the right choice?",
            "society":"Does anonymity make discourse better?",
            "culture":"Do memes count as modern art?",
            "politics":"Do term limits make democracy stronger?",
            "tech":"Is AI more tool or threat?",
            "future":"Will humans settle Mars in your lifetime?"
        }
        return stock.get(next_theme, "Is disagreement a sign of progress?")
    user_prompt = f"Generate one question (<120 chars) for this hour.\nRecent headline: {last_headline[:180]}\nTheme: {next_theme}"
    try:
        resp = ai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":user_prompt}],
            temperature=0.7,
            max_tokens=60
        )
        q = resp.choices[0].message.content.strip().strip('"')
        return q[:120]
    except Exception:
        return "Is disagreement a sign of progress?"

def current_theme_for_hour(dt: datetime) -> str:
    base = int(dt.astimezone(timezone.utc).timestamp()) // 3600
    return THEMES[base % len(THEMES)]

# -- Hourly lifecycle --

GRACE_SECONDS_AFTER_HOUR = 8  # show "Top Answer" briefly before purge

def ensure_current_hour_question():
    now = now_tz()
    hk = hour_key_for(now)
    got = supabase.table("hour_questions").select("*").eq("hour_key", hk).limit(1).execute().data
    if got:
        return got[0]
    theme = current_theme_for_hour(now)
    headline = "Latest hour headline."
    q_text = ai_generate_question(headline, theme)
    expires = end_of_hour(now).astimezone(timezone.utc)
    data = {
        "hour_key": hk,
        "text": q_text,
        "expires_at": expires.isoformat(),
        "open_mode": True
    }
    ins = supabase.table("hour_questions").insert(data).execute().data
    return ins[0]

def purge_expired():
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=GRACE_SECONDS_AFTER_HOUR)
    expired = supabase.table("hour_questions").select("id").lt("expires_at", cutoff.isoformat()).execute().data or []
    if expired:
        ids = [row["id"] for row in expired]
        supabase.table("hour_questions").delete().in_("id", ids).execute()

def hourly_tick():
    ensure_current_hour_question()
    purge_expired()

scheduler = BackgroundScheduler()
scheduler.add_job(hourly_tick, "interval", seconds=30, id="hourly_tick", max_instances=1, coalesce=True)
scheduler.start()

# -- FastAPI app --

app = FastAPI(title="AgorHour")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# minimal frontend
INDEX_HTML = """<!DOCTYPE html>
<html>
<head><meta charset='utf-8'><title>AgorHour</title></head>
<body>
<h1>AgorHour</h1>
<div id='question'>Loading...</div>
<script>
fetch('/api/hour/current').then(r=>r.json()).then(data=>{
  document.getElementById('question').innerText = data.hour.text;
});
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML

# -- API Endpoints --

@app.post("/api/session")
def create_or_get_session():
    seed = random.randint(0, 999_999)
    ins = supabase.table("anon_sessions").insert({"avatar_seed": seed}).execute().data
    s = ins[0]
    s["avatar"] = avatar_from_seed(s["avatar_seed"])
    return s

@app.get("/api/hour/current")
def current_hour(include_answers: int = 1):
    h = ensure_current_hour_question()
    now = now_tz()
    end = end_of_hour(now).astimezone(TZINFO)
    seconds_left = max(0, int((end - now).total_seconds()))
    resp = {
        "hour": {"id": h["id"], "hour_key": h["hour_key"], "text": h["text"], "expires_at": h["expires_at"], "open_mode": h.get("open_mode", True)},
        "countdown_seconds": seconds_left
    }
    if include_answers:
        ans = (supabase.table("answers")
                .select("id, session_id, text, stance, exposed, created_at")
                .eq("hour_id", h["id"])
                .order("created_at", desc=False)
                .execute().data) or []
        out = []
        for a in ans:
            sc = score_for_answer(a["id"])
            sess = supabase.table("anon_sessions").select("avatar_seed").eq("id", a["session_id"]).limit(1).execute().data
            avatar = avatar_from_seed((sess[0]["avatar_seed"] if sess else 0))
            a2 = dict(a)
            a2["score"] = sc
            a2["avatar"] = None if a["exposed"] else avatar
            a2["exposed_badge"] = bool(a["exposed"])
            out.append(a2)
        resp["answers"] = out
    return resp

@app.post("/api/hour/answer")
def post_answer(payload: Dict[str, Any] = Body(...)):
    """payload: { session_id, stance (optional if open_mode=true), text, force_expose=false }"""
    session_id = payload.get("session_id")
    text = (payload.get("text") or "").strip()
    stance = payload.get("stance")
    force_expose = bool(payload.get("force_expose", False))
    if not session_id or not text:
        raise HTTPException(400, "Missing session_id or text.")
    h = ensure_current_hour_question()
    already = (supabase.table("answers")
               .select("id").eq("hour_id", h["id"]).eq("session_id", session_id).limit(1).execute().data)
    if already:
        raise HTTPException(409, "Already answered this hour.")
    if h.get("open_mode", True) is False and stance not in ("AGREE","DISAGREE"):
        raise HTTPException(400, "Stance required.")
    color = meter_color(text)
    exposed = False
    if color == "red" and not force_expose:
        return JSONResponse({"ok": False, "meter": "red", "requires_expose": True}, status_code=403)
    if color == "red" and force_expose:
        exposed = True
    ins = supabase.table("answers").insert({
        "hour_id": h["id"],
        "session_id": session_id,
        "stance": stance,
        "text": text,
        "exposed": exposed
    }).execute().data
    return {"ok": True, "answer": ins[0], "meter": color}

@app.post("/api/answer/react")
def react(payload: Dict[str, Any] = Body(...)):
    """payload: { session_id, answer_id, kind: 'LIKE'|'UNLIKE' }"""
    session_id = payload.get("session_id")
    answer_id = payload.get("answer_id")
    kind = payload.get("kind")
    if kind not in ("LIKE","UNLIKE"):
        raise HTTPException(400, "Invalid reaction kind.")
    if not session_id or not answer_id:
        raise HTTPException(400, "Missing session_id or answer_id.")
    existing = supabase.table("reactions").select("id").eq("answer_id", answer_id).eq("session_id", session_id).execute().data
    if existing:
        supabase.table("reactions").delete().eq("answer_id", answer_id).eq("session_id", session_id).execute()
    supabase.table("reactions").insert({"answer_id": answer_id, "session_id": session_id, "kind": kind}).execute()
    return {"ok": True, "score": score_for_answer(answer_id)}

@app.get("/api/hour/top")
def top_answer():
    h = ensure_current_hour_question()
    ans = (supabase.table("answers")
           .select("id, text")
           .eq("hour_id", h["id"]).execute().data) or []
    if not ans:
        return {"ok": False}
    best = max(ans, key=lambda a: score_for_answer(a["id"]))
    return {"ok": True, "answer": {"id": best["id"], "text": best["text"], "score": score_for_answer(best["id"])}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agorhour:app", host=HOST, port=PORT)
