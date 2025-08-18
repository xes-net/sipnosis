"""AgorHour — single-file Python MVP (backend + minimal frontend + hourly AI + Supabase)

USAGE (one copy-paste):

1. Save as agorhour.py, then run:  python agorhour.py
1. Required ENV (export or .env):
   SUPABASE_URL=…
   SUPABASE_SERVICE_ROLE_KEY=…     # server key (NOT anon)
   
   # EITHER provide direct Postgres URL to auto-create tables (recommended):
   
   SUPABASE_DB_URL=postgresql://…  # Project Settings → Database → Connection string
   
   # AI (optional but recommended for hourly question generation):
   
   OPENAI_API_KEY=sk-…
   OPENAI_MODEL=gpt-4o-mini          # or gpt-4o, gpt-3.5-turbo, etc.
   
   # Security for manual cron trigger:
   
   AGORHOUR_CRON_SECRET=some-long-random
   
   # Optional:
   
   HOST=0.0.0.0
   PORT=8080
   TZ=Europe/Rome

WHAT YOU GET:

- FastAPI server with endpoints per spec:
  /api/session, /api/hour/current, /api/hour/answer, /api/answer/react, /api/hour/top
  - /api/cron/hourly  (protected; external cron) and built-in scheduler (APScheduler)
- Supabase persistence (tables auto-created if SUPABASE_DB_URL provided; else skip)
- Ephemerality: auto-seed one question/hour, purge expired hour data shortly after hour end
- Working Meter (client & server), Expose confirmation for RED posts
- Minimal mobile-first UI + PWA (manifest + service worker) using Tailwind CDN + polling
- No-history rule honored: data wiped after the hour

NOTE:

- Uses Supabase REST with service role; Realtime is approximated by client polling (2s).
- If you insist on Supabase Realtime channels, wire your Next.js client later; the DB schema matches.
"""

# — Auto-install missing dependencies (keeps this truly one-paste) —

import importlib, subprocess, sys
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
if need("python-dotenv","dotenv"): missing += ["python-dotenv"]
if need("apscheduler"): missing += ["apscheduler"]
if need("supabase"): missing += ["supabase"]
if need("psycopg2"): missing += ["psycopg2-binary"]
if need("openai"): missing += ["openai"]
if missing: pip_install(*missing)

# — Imports —

import os, json, re, random, string
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException, Body, Depends
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import psycopg2
from psycopg2.extras import execute_batch

from supabase import create_client, Client

# AI

from openai import OpenAI

# — Config / Env —

load_dotenv()
HOST = os.getenv("HOST","0.0.0.0")
PORT = int(os.getenv("PORT","8080"))
TZ = os.getenv("TZ","Europe/Rome")
TZINFO = ZoneInfo(TZ)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")  # optional, for DDL
AGORHOUR_CRON_SECRET = os.getenv("AGORHOUR_CRON_SECRET","change-me")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL","gpt-4o-mini")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in env.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
ai_client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# — Schema (per brief) —

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

# — Helpers —

def now_tz() -> datetime:
    return datetime.now(tz=TZINFO)

def hour_key_for(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H")  # canonical in UTC

def hour_window(dt: datetime) -> (datetime, datetime):
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

EMOJI_POOL = ["😶","🫥","🫣","🫡","😏","😐","🙃","😎","🥸","🤖","👻","👽","🐸","🦊","🐼","🐨","🦉","🐺","🦄","🐙"]

def avatar_from_seed(seed: int) -> Dict[str, Any]:
    hue = seed % 360
    emoji = EMOJI_POOL[seed % len(EMOJI_POOL)]
    return {"hsl": f"hsl({hue} 70% 50%)", "emoji": emoji}

# — Working Meter (server-side mirror of client logic) —

HARD_RED_PATTERNS = [
    r"\b(kill|murder|rape|lynch|gas|exterminate)\b",
    r"\b(doxx|address|phone|ssn)\b",
    r"\b(slur1|slur2|slur3)\b",  # placeholder: keep policy list server-side
]
MILD_YELLOW_PATTERNS = [
    r"[A-Z]{5,}",
    r"[!?.]{3,}",
    r"\b(damn|hell|crap)\b",
]
def meter_color(text: str) -> str:
    t = text.strip().lower()
    if not t: return "red"
    for p in HARD_RED_PATTERNS:
        if re.search(p, t): return "red"
    for p in MILD_YELLOW_PATTERNS:
        if re.search(p, t): return "yellow"
    if len(text) > 110: return "yellow"
    return "green"

# — AI Question Generator —

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
        # Fallback deterministic stock question
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
        return stock.get(next_theme,"Is disagreement a sign of progress?")
    user_prompt = f"Generate one question (<120 chars) for this hour.\nRecent headline: {last_headline[:180]}\nTheme: {next_theme}"
    resp = ai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":user_prompt}],
        temperature=0.7,
        max_tokens=60
    )
    q = resp.choices[0].message.content.strip().strip('"')
    return q[:120]

def current_theme_for_hour(dt: datetime) -> str:
    # rotate deterministically by absolute hour number
    base = int(dt.astimezone(timezone.utc).strftime("%s")) // 3600
    return THEMES[base % len(THEMES)]

# — Hourly lifecycle —

GRACE_SECONDS_AFTER_HOUR = 8  # show "Top Answer" briefly before purge

def ensure_current_hour_question():
    now = now_tz()
    hk = hour_key_for(now)
    # Do we already have it?
    got = supabase.table("hour_questions").select("*").eq("hour_key", hk).limit(1).execute().data
    if got:
        return got[0]
    # Create new question
    theme = current_theme_for_hour(now)
    # In production you might fetch real headline here; keep empty or a placeholder
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
    # Purge anything with expires_at < now - small grace
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=GRACE_SECONDS_AFTER_HOUR)
    # Fetch expired ids for cascade review (answers/reactions have ON DELETE CASCADE)
    expired = supabase.table("hour_questions").select("id").lt("expires_at", cutoff.isoformat()).execute().data or []
    if expired:
        ids = [row["id"] for row in expired]
        # Delete expired hours → cascades
        supabase.table("hour_questions").delete().in_("id", ids).execute()

def hourly_tick():
    ensure_current_hour_question()
    purge_expired()

# Scheduler (runs every 30s so we don't miss exact boundaries even on cheap hosts)

scheduler = BackgroundScheduler()
scheduler.add_job(hourly_tick, "interval", seconds=30, id="hourly_tick", max_instances=1, coalesce=True)
scheduler.start()

# — FastAPI app —

app = FastAPI(title="AgorHour")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# — API Endpoints (per brief) —

@app.post("/api/session")
def create_or_get_session():
    # create a new anon session each time (stateless client can store id)
    seed = random.randint(0, 999999)
    ins = supabase.table("anon_sessions").insert({"avatar_seed": seed}).execute().data
    s = ins[0]
    s["avatar"] = avatar_from_seed(s["avatar_seed"])
    return s

@app.get("/api/hour/current")
def current_hour(include_answers: int = 1):
    h = ensure_current_hour_question()
    # compute countdown (seconds left in local TZ)
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
        # Annotate with score and avatar
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
    """
    payload: { session_id, stance (optional if open_mode=true), text, force_expose=false }
    """
    session_id = payload.get("session_id")
    text = (payload.get("text") or "").strip()
    stance = payload.get("stance")
    force_expose = bool(payload.get("force_expose", False))
    if not session_id or not text:
        raise HTTPException(400, "Missing session_id or text.")
    h = ensure_current_hour_question()
    # one per session per hour
    already = (supabase.table("answers")
        .select("id").eq("hour_id", h["id"]).eq("session_id", session_id).limit(1).execute().data)
    if already:
        raise HTTPException(409, "Already answered this hour.")
    # stance requirement if open_mode=false
    if h.get("open_mode", True) is False and stance not in ("AGREE","DISAGREE"):
        raise HTTPException(400, "Stance required.")
    # meter
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
    """
    payload: { session_id, answer_id, kind: 'LIKE'|'UNLIKE' }
    """
    session_id = payload.get("session_id")
    answer_id = payload.get("answer_id")
    kind = payload.get("kind")
    if kind not in ("LIKE","UNLIKE"):
        raise HTTPException(400, "Invalid reaction kind.")
    if not session_id or not answer_id:
        raise HTTPException(400, "Missing session_id or answer_id.")
    # remove any existing reaction from same session to this answer, then insert new
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
        return {"top": None}
    scored = [(a["id"], a["text"], score_for_answer(a["id"])) for a in ans]
    scored.sort(key=lambda x: x[2], reverse=True)
    best = scored[0]
    return {"top": {"answer_id": best[0], "text": best[1], "score": best[2]}}

@app.post("/api/cron/hourly")
def cron_hourly(req: Request):
    if req.headers.get("x-agorhour-secret") != AGORHOUR_CRON_SECRET:
        raise HTTPException(401, "Unauthorized")
    hourly_tick()
    return {"ok": True}

# — Minimal Frontend (PWA) —

INDEX_HTML = """<!DOCTYPE html>

<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0b0b0c"/>
<title>AgorHour</title>
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', ()=>navigator.serviceWorker.register('/sw.js'));
}}
</script>
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root {{
  --bg:#0b0b0c; --card:#151518; --txt:#eaeaea; --g:#22c55e; --y:#eab308; --r:#ef4444;
}}
body {{ background:var(--bg); color:var(--txt); }}
.card {{ background:var(--card); border-radius:14px; }}
.meter-bar {{ height:8px; border-radius:6px; background:#333; overflow:hidden; }}
.meter-fill {{ height:8px; width:100%; }}
avatar {{
  width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:18px;
}}
.badge-exposed {{ background:var(--r); color:black; font-weight:700; padding:0 8px; border-radius:10px; font-size:12px; }}
.btn {{ background:#2a2a2f; padding:10px 14px; border-radius:10px; }}
.btn[disabled] {{ opacity:.5 }}
</style>
</head>
<body class="min-h-screen">
<div class="max-w-xl mx-auto p-4">
  <header class="flex items-center justify-between mb-4">
    <h1 class="text-xl font-semibold">AgorHour</h1>
    <div id="countdown" class="text-sm text-gray-300">--:--</div>
  </header>

  <main class="card p-4">
    <div id="question" class="text-lg font-medium leading-snug"></div>
    <div id="stanceWrap" class="mt-3 hidden">
      <label class="mr-3"><input type="radio" name="stance" value="AGREE"> <span class="ml-1">AGREE</span></label>
      <label class="mr-3"><input type="radio" name="stance" value="DISAGREE"> <span class="ml-1">DISAGREE</span></label>
    </div>
    <div class="mt-3">
      <textarea id="answer" maxlength="120" placeholder="Say it in 120 characters…" class="w-full p-3 rounded bg-[#101013] border border-[#2a2a2f] outline-none"></textarea>
      <div class="meter-bar mt-2"><div id="meter" class="meter-fill" style="background:var(--g);"></div></div>
      <div class="text-xs mt-1 text-gray-400"><span id="chars">0</span>/120</div>
    </div>
    <div class="mt-3 flex items-center gap-2">
      <button id="submit" class="btn">Post</button>
      <div id="exposeNote" class="text-xs text-red-400 hidden">RED → you must confirm expose to post.</div>
    </div>
  </main>

  <section class="mt-4 card p-4">
    <h2 class="text-sm text-gray-300 mb-2">Live answers</h2>
    <div id="feed" class="flex flex-col gap-2"></div>
  </section>

  <footer class="mt-6 text-xs text-gray-500">
    <div>Top answer will be revealed at hour end, then everything disappears.</div>
  </footer>
</div>

<script>
const API = location.origin;
let session = null;
let currentHourId = null;
let alreadyPosted = false;

function hslStr(hsl) {{ return hsl; }}

async function ensureSession(){
  const s = localStorage.getItem('agorhour_session');
  if (s) {{ session = JSON.parse(s); return; }}
  const r = await fetch(API+'/api/session', {method:'POST'});
  session = await r.json();
  localStorage.setItem('agorhour_session', JSON.stringify(session));
}}

function meterColor(t){
  const text = (t||'').trim();
  if (!text) return 'red';
  if (/[A-Z]{5,}/.test(text) || /[!?.]{3,}/.test(text) || /(damn|hell|crap)/i.test(text) || text.length>110) return 'yellow';
  if (/(kill|murder|rape|lynch|gas|exterminate|doxx|address|phone|ssn)/i.test(text)) return 'red';
  return 'green';
}}

function setMeter(color){
  const el=document.getElementById('meter');
  el.style.background = color==='green'?'var(--g)':(color==='yellow'?'var(--y)':'var(--r)');
}}

function fmtCountdown(sec){
  const m = Math.floor(sec/60).toString().padStart(2,'0');
  const s = (sec%60).toString().padStart(2,'0');
  return m+':'+s;
}}

async function loadCurrent(includeAnswers=1){
  const r = await fetch(API+'/api/hour/current?include_answers='+includeAnswers);
  const data = await r.json();
  currentHourId = data.hour.id;
  document.getElementById('question').textContent = data.hour.text;
  document.getElementById('countdown').textContent = fmtCountdown(data.countdown_seconds);
  document.getElementById('stanceWrap').classList.toggle('hidden', !!data.hour.open_mode);
  if (includeAnswers) renderFeed(data.answers||[]);
  // If very near hour end, prefetch top once
  if (data.countdown_seconds <= 3) showTopAndWipeSoon();
}}

function avatarNode(a){
  const wrap = document.createElement('div');
  wrap.className='avatar';
  if (a.exposed_badge){
    const b = document.createElement('span'); b.className='badge-exposed'; b.textContent='EXPOSED'; wrap.appendChild(b);
  } else {
    wrap.style.background = a.avatar?.hsl || 'hsl(0 0% 40%)';
    wrap.textContent = a.avatar?.emoji || '😶';
  }
  return wrap;
}}

function renderFeed(list){
  const feed = document.getElementById('feed'); feed.innerHTML='';
  list.forEach(a => {
    const row = document.createElement('div');
    row.className='flex items-start gap-2 p-2 rounded bg-[#101013]';
    const av = avatarNode(a);
    const body = document.createElement('div'); body.className='flex-1';
    const meta = document.createElement('div'); meta.className='text-xs text-gray-400';
    meta.textContent = (a.stance||'') + (a.stance?' · ':'') + 'score '+a.score;
    const text = document.createElement('div'); text.className='text-sm'; text.textContent = a.text;
    body.appendChild(meta); body.appendChild(text);
    const like = document.createElement('button'); like.className='btn text-xs'; like.textContent='Like';
    like.onclick = ()=>react(a.id,'LIKE');
    const unlike = document.createElement('button'); unlike.className='btn text-xs'; unlike.textContent='Unlike';
    unlike.onclick = ()=>react(a.id,'UNLIKE');
    row.appendChild(av); row.appendChild(body); row.appendChild(like); row.appendChild(unlike);
    feed.appendChild(row);
  });
}}

async function react(answer_id, kind){
  if (!session) return;
  await fetch(API+'/api/answer/react', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id:session.id, answer_id, kind})
  });
  loadCurrent(1);
}}

async function postAnswer(){
  if (alreadyPosted) return;
  const txt = document.getElementById('answer').value.trim();
  const color = meterColor(txt);
  const data = {
    session_id: session.id, text: txt, force_expose: false
  };
  const stanceEl = document.querySelector('input[name="stance"]:checked');
  if (!document.getElementById('stanceWrap').classList.contains('hidden')) {
    data.stance = stanceEl?.value || null;
  }
  let r = await fetch(API+'/api/hour/answer', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)
  });
  if (r.status===403){
    const p = await r.json();
    if (p.requires_expose){
      if (confirm('Your text is RED. Post anyway and be EXPOSED for this question?')) {
        data.force_expose = true;
        r = await fetch(API+'/api/hour/answer', {
          method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)
        });
      } else return;
    }
  }
  if (r.ok){
    alreadyPosted = true;
    document.getElementById('submit').setAttribute('disabled','true');
    document.getElementById('answer').setAttribute('disabled','true');
    loadCurrent(1);
  } else {
    alert('Error posting.');
  }
}}

async function showTopAndWipeSoon(){
  const r = await fetch(API+'/api/hour/top'); const d = await r.json();
  if (d.top){
    alert('Top Answer: '+d.top.text+'  (score '+d.top.score+')');
  }
}}

function tick(){
  // pull current & feed frequently (polling)
  loadCurrent(1);
}}

document.addEventListener('DOMContentLoaded', async ()=>{
  await ensureSession();
  // UI bindings
  const ta = document.getElementById('answer');
  const submit = document.getElementById('submit');
  const exposeNote = document.getElementById('exposeNote');
  const chars = document.getElementById('chars');
  ta.addEventListener('input', ()=>{
    chars.textContent = ta.value.length;
    const c = meterColor(ta.value);
    setMeter(c);
    exposeNote.classList.toggle('hidden', c!=='red');
  });
  submit.addEventListener('click', postAnswer);
  setMeter('green');
  loadCurrent(1);
  setInterval(tick, 2000);
});
</script>

</body>
</html>
"""

MANIFEST = {
    "name": "AgorHour",
    "short_name": "AgorHour",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0b0b0c",
    "theme_color": "#0b0b0c",
    "icons": []
}

SW_JS = """
self.addEventListener('install', e=>self.skipWaiting());
self.addEventListener('activate', e=>self.clients.claim());
self.addEventListener('fetch', ()=>{});
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML

@app.get("/manifest.webmanifest", response_class=JSONResponse)
def manifest():
    return MANIFEST

@app.get("/sw.js", response_class=PlainTextResponse)
def sw():
    return SW_JS

# — Start server —

if __name__ == "__main__":
    print("AgorHour server starting …")
    print(f"Listening on http://{HOST}:{PORT}  (TZ={TZ})")
    # Prime hour on boot
    hourly_tick()
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
