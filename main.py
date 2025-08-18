"""
AgorHour — one-file Python app (FastAPI + Supabase + hourly lifecycle + minimal PWA)

WHAT YOU ALREADY DID (good):
- Filled 4 Secrets on Replit:
  DATABASE_URL = postgresql://postgres....:5432/postgres
  OPENAI_API_KEY = (leave empty to stay free)
  SUPABASE_SERVICE_ROLE_KEY = <service_role key from Supabase>
  SUPABASE_URL = https://<project>.supabase.co

HOW TO RUN:
- Paste this whole file as main.py in Replit, then click Run.
- Open the web preview URL Replit shows → AgorHour is live.

"""

# ---- tiny self-installer so one paste works ----
import importlib, subprocess, sys
def need(pkg, import_name=None):
    try: importlib.import_module(import_name or pkg); return False
    except ImportError: return True
to_install=[]
if need("fastapi"): to_install+=["fastapi"]
if need("uvicorn"): to_install+=["uvicorn"]
if need("python-dotenv","dotenv"): to_install+=["python-dotenv"]
if need("apscheduler"): to_install+=["apscheduler"]
if need("supabase"): to_install+=["supabase"]
if need("psycopg2"): to_install+=["psycopg2-binary"]
if need("openai"): to_install+=["openai"]
if to_install: subprocess.check_call([sys.executable,"-m","pip","install",*to_install])

# ---- imports ----
import os, re, random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

from fastapi import FastAPI, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from supabase import create_client, Client
import psycopg2

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ---- env ----
load_dotenv()
HOST = os.getenv("HOST","0.0.0.0")
PORT = int(os.getenv("PORT","8000"))  # Replit likes 8000
TZINFO = ZoneInfo(os.getenv("TZ","Europe/Rome"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
# accept either SUPABASE_DB_URL or DATABASE_URL (your 1st box)
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL","gpt-4o-mini")

if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and SUPABASE_DB_URL):
    print("Missing required env. Need SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and DATABASE_URL/SUPABASE_DB_URL.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
ai_client: Optional[Any] = OpenAI(api_key=OPENAI_API_KEY) if (OPENAI_API_KEY and OpenAI) else None

# ---- schema ----
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

create index if not exists idx_hour_questions_hour_key on hour_questions(hour_key);
create index if not exists idx_answers_hour on answers(hour_id);
create index if not exists idx_reactions_answer on reactions(answer_id);
"""

def run_ddl():
    conn = psycopg2.connect(SUPABASE_DB_URL); conn.autocommit=True
    with conn.cursor() as cur: cur.execute(DDL_SQL)
    conn.close()
run_ddl()

# ---- helpers ----
def now_tz(): return datetime.now(tz=TZINFO)
def hour_key(dt): return dt.astimezone(timezone.utc).strftime("%Y%m%d%H")
def end_of_hour(dt): return dt.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)

EMOJI = ["😶","🫥","🫡","😐","🙃","😎","🥸","🤖","👻","🦊","🐼","🦉","🐺","🦄","🐙"]
def avatar(seed:int): return {"hsl": f"hsl({seed%360} 70% 50%)", "emoji": EMOJI[seed%len(EMOJI)]}

def score(answer_id:str)->int:
    likes = supabase.table("reactions").select("id").eq("answer_id",answer_id).eq("kind","LIKE").execute().data or []
    unlikes = supabase.table("reactions").select("id").eq("answer_id",answer_id).eq("kind","UNLIKE").execute().data or []
    return len(likes)-len(unlikes)

# working meter
HARD = [r"\b(kill|murder|rape|lynch|gas|exterminate)\b", r"\b(doxx|address|phone|ssn)\b"]
SOFT = [r"[A-Z]{5,}", r"[!?.]{3,}", r"\b(damn|hell|crap)\b"]
def meter(text:str)->str:
    t=text.strip().lower()
    if not t: return "red"
    for p in HARD:
        if re.search(p,t): return "red"
    for p in SOFT:
        if re.search(p,t): return "yellow"
    if len(text)>110: return "yellow"
    return "green"

# AI question generator (optional)
SYSTEM = (
"You are AgorHour’s Question Master. ONE concise debate question.\n"
"- <=120 chars, plain English, neutral→provocative, safe-for-work.\n"
"- Rotate themes: life, love, food, work, ethics, society, culture, politics, tech, future.\n"
"- Output only the question."
)
THEMES = ["life","love","food","work","ethics","society","culture","politics","tech","future"]

def theme_for(dt):  # deterministic rotation
    return THEMES[(int(dt.astimezone(timezone.utc).timestamp())//3600) % len(THEMES)]

def ai_question():
    if not ai_client:
        stock = {
            "life":"Is happiness more comfort or challenge?",
            "love":"Can long-distance love really last?",
            "food":"Is fast food killing tradition or saving time?",
            "work":"Should employers track digital productivity?",
            "ethics":"Is lying ever the right choice?",
            "society":"Does anonymity improve debate?",
            "culture":"Do memes count as modern art?",
            "politics":"Do term limits make democracy stronger?",
            "tech":"Is AI more tool or threat?",
            "future":"Will humans settle Mars in your lifetime?"
        }
        return stock.get(theme_for(now_tz()), "Is disagreement a sign of progress?")
    msg_user = f"Generate a question <120 chars. Theme: {theme_for(now_tz())}. Recent headline: N/A."
    r = ai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":msg_user}],
        temperature=0.7, max_tokens=60
    )
    q = r.choices[0].message.content.strip().strip('"')
    return q[:120]

# hour management
def ensure_hour():
    hk = hour_key(now_tz())
    got = supabase.table("hour_questions").select("*").eq("hour_key",hk).limit(1).execute().data
    if got: return got[0]
    q = ai_question()
    expires = end_of_hour(now_tz()).astimezone(timezone.utc).isoformat()
    ins = supabase.table("hour_questions").insert({"hour_key":hk,"text":q,"expires_at":expires,"open_mode":True}).execute().data
    return ins[0]

def purge_expired():
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=8)
    exp = supabase.table("hour_questions").select("id").lt("expires_at",cutoff.isoformat()).execute().data or []
    if exp:
        ids=[e["id"] for e in exp]
        supabase.table("hour_questions").delete().in_("id",ids).execute()

def hourly_tick():
    ensure_hour(); purge_expired()

sched = BackgroundScheduler()
sched.add_job(hourly_tick,"interval",seconds=30, coalesce=True, max_instances=1)
sched.start()

# ---- API ----
app = FastAPI(title="AgorHour")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

@app.post("/api/session")
def api_session():
    seed = random.randint(0, 1_000_000)
    s = supabase.table("anon_sessions").insert({"avatar_seed":seed}).execute().data[0]
    s["avatar"]=avatar(seed)
    return s

@app.get("/api/hour/current")
def api_current(include_answers:int=1):
    h = ensure_hour()
    end_local = end_of_hour(now_tz())
    sec_left = max(0,int((end_local - now_tz()).total_seconds()))
    resp = {"hour":{"id":h["id"],"hour_key":h["hour_key"],"text":h["text"],"expires_at":h["expires_at"],"open_mode":h.get("open_mode",True)},
            "countdown_seconds":sec_left}
    if include_answers:
        ans = (supabase.table("answers").select("id,session_id,text,stance,exposed,created_at")
               .eq("hour_id",h["id"]).order("created_at").execute().data) or []
        out=[]
        for a in ans:
            sess = supabase.table("anon_sessions").select("avatar_seed").eq("id",a["session_id"]).limit(1).execute().data
            av = avatar(sess[0]["avatar_seed"]) if sess else avatar(0)
            a2 = dict(a); a2["score"]=score(a["id"]); a2["avatar"]=None if a["exposed"] else av; a2["exposed_badge"]=bool(a["exposed"])
            out.append(a2)
        resp["answers"]=out
    return resp

@app.post("/api/hour/answer")
def api_answer(payload:Dict[str,Any]=Body(...)):
    sid = payload.get("session_id"); txt=(payload.get("text") or "").strip()
    stance = payload.get("stance"); force = bool(payload.get("force_expose",False))
    if not sid or not txt: raise HTTPException(400,"Missing session_id or text.")
    h=ensure_hour()
    already = supabase.table("answers").select("id").eq("hour_id",h["id"]).eq("session_id",sid).limit(1).execute().data
    if already: raise HTTPException(409,"Already answered this hour.")
    if h.get("open_mode",True) is False and stance not in ("AGREE","DISAGREE"):
        raise HTTPException(400,"Stance required.")
    m = meter(txt); exposed = (m=="red" and force)
    if m=="red" and not force:
        return JSONResponse({"ok":False,"meter":"red","requires_expose":True}, status_code=403)
    ins = supabase.table("answers").insert({"hour_id":h["id"],"session_id":sid,"stance":stance,"text":txt,"exposed":exposed}).execute().data[0]
    return {"ok":True,"answer":ins,"meter":m}

@app.post("/api/answer/react")
def api_react(payload:Dict[str,Any]=Body(...)):
    sid = payload.get("session_id"); aid=payload.get("answer_id"); kind=payload.get("kind")
    if kind not in ("LIKE","UNLIKE"): raise HTTPException(400,"Invalid reaction kind.")
    if not sid or not aid: raise HTTPException(400,"Missing session_id or answer_id.")
    supabase.table("reactions").delete().eq("answer_id",aid).eq("session_id",sid).execute()
    supabase.table("reactions").insert({"answer_id":aid,"session_id":sid,"kind":kind}).execute()
    return {"ok":True,"score":score(aid)}

@app.get("/api/hour/top")
def api_top():
    h=ensure_hour()
    ans=(supabase.table("answers").select("id,text").eq("hour_id",h["id"]).execute().data) or []
    if not ans: return {"top":None}
    best=max(((a["id"],a["text"],score(a["id"])) for a in ans), key=lambda x:x[2])
    return {"top":{"answer_id":best[0],"text":best[1],"score":best[2]}}

# ----- minimal PWA UI -----
INDEX_HTML = """<!doctype html><html><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AgorHour</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>:root{--bg:#0b0b0c;--card:#151518;--txt:#eaeaea;--g:#22c55e;--y:#eab308;--r:#ef4444}
body{background:var(--bg);color:var(--txt)}.card{background:var(--card);border-radius:14px}
.meter{height:8px;border-radius:6px;background:#333;overflow:hidden}.fill{height:8px}
.avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px}
.badge{background:var(--r);color:#000;border-radius:10px;padding:0 8px;font-size:12px;font-weight:700}</style>
</head><body><div class="max-w-xl mx-auto p-4">
<header class="flex justify-between mb-4"><h1 class="text-xl font-semibold">AgorHour</h1><div id="cd" class="text-sm text-gray-300">--:--</div></header>
<main class="card p-4">
  <div id="q" class="text-lg font-medium"></div>
  <div id="stanceWrap" class="mt-3 hidden">
    <label class="mr-3"><input type="radio" name="s" value="AGREE"> AGREE</label>
    <label class="mr-3"><input type="radio" name="s" value="DISAGREE"> DISAGREE</label>
  </div>
  <textarea id="t" maxlength="120" placeholder="Say it in 120 chars…" class="w-full mt-3 p-3 rounded bg-[#101013] border border-[#2a2a2f] outline-none"></textarea>
  <div class="meter mt-2"><div id="m" class="fill" style="background:var(--g)"></div></div>
  <div class="text-xs mt-1 text-gray-400"><span id="c">0</span>/120</div>
  <button id="post" class="mt-3 bg-[#2a2a2f] px-3 py-2 rounded">Post</button>
  <div id="note" class="text-xs text-red-400 mt-1 hidden">RED → confirm expose to post.</div>
</main>
<section class="mt-4 card p-4"><h2 class="text-sm text-gray-300 mb-2">Live answers</h2><div id="feed" class="flex flex-col gap-2"></div></section>
<footer class="mt-6 text-xs text-gray-500">Top answer shows at hour end; then all disappears.</footer>
</div>
<script>
const API=location.origin; let session=null, posted=false;
function meterColor(t){t=(t||'').trim(); if(!t) return 'red';
 if(/[A-Z]{5,}/.test(t)||/[!?.]{3,}/.test(t)||/(damn|hell|crap)/i.test(t)||t.length>110) return 'yellow';
 if(/(kill|murder|rape|lynch|gas|exterminate|doxx|address|phone|ssn)/i.test(t)) return 'red'; return 'green';}
function setMeter(c){document.getElementById('m').style.background=c==='green'?'var(--g)':(c==='yellow'?'var(--y)':'var(--r)')}
function fmt(s){const m=String(Math.floor(s/60)).padStart(2,'0'), x=String(s%60).padStart(2,'0'); return m+':'+x}
async function ensureSession(){if(localStorage.s){session=JSON.parse(localStorage.s);return}
 let r=await fetch(API+'/api/session',{method:'POST'}); session=await r.json(); localStorage.s=JSON.stringify(session);}
function avNode(a){const d=document.createElement('div'); d.className='avatar'; if(a.exposed_badge){d.classList.add('badge'); d.textContent='EXPOSED'} else {d.style.background=a.avatar?.hsl||'hsl(0 0% 40%)'; d.textContent=a.avatar?.emoji||'😶'} return d}
function renderFeed(list){const f=document.getElementById('feed'); f.innerHTML=''; list.forEach(a=>{const row=document.createElement('div');row.className='flex items-start gap-2 p-2 rounded bg-[#101013]';
 const av=avNode(a); const b=document.createElement('div'); b.className='flex-1'; const meta=document.createElement('div'); meta.className='text-xs text-gray-400'; meta.textContent=(a.stance||'')+(a.stance?' · ':'')+'score '+a.score; const txt=document.createElement('div'); txt.className='text-sm'; txt.textContent=a.text;
 const like=document.createElement('button'); like.className='bg-[#2a2a2f] px-2 py-1 rounded text-xs'; like.textContent='Like'; like.onclick=()=>react(a.id,'LIKE');
 const unlike=document.createElement('button'); unlike.className='bg-[#2a2a2f] px-2 py-1 rounded text-xs'; unlike.textContent='Unlike'; unlike.onclick=()=>react(a.id,'UNLIKE');
 b.appendChild(meta); b.appendChild(txt); row.appendChild(av); row.appendChild(b); row.appendChild(like); row.appendChild(unlike); f.appendChild(row);});}
async function load(){const r=await fetch(API+'/api/hour/current?include_answers=1'); const d=await r.json(); document.getElementById('q').textContent=d.hour.text; document.getElementById('cd').textContent=fmt(d.countdown_seconds); document.getElementById('stanceWrap').classList.toggle('hidden',!!d.hour.open_mode); renderFeed(d.answers||[]); if(d.countdown_seconds<=3){const t=await fetch(API+'/api/hour/top'); const x=await t.json(); if(x.top) alert('Top: '+x.top.text+' ('+x.top.score+')');}}
async function react(id,k){await fetch(API+'/api/answer/react',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:session.id,answer_id:id,kind:k})}); load();}
async function post(){ if(posted) return; const txt=document.getElementById('t').value.trim(); const col=meterColor(txt); let body={session_id:session.id,text:txt,force_expose:false}; const st=document.querySelector('input[name="s"]:checked'); if(!document.getElementById('stanceWrap').classList.contains('hidden')) body.stance=st?.value||null;
 let r=await fetch(API+'/api/hour/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.status===403){const p=await r.json(); if(p.requires_expose && confirm('RED. Post and be EXPOSED for this hour?')){body.force_expose=true; r=await fetch(API+'/api/hour/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});} else return;}
 if(r.ok){posted=true; document.getElementById('t').disabled=true; document.getElementById('post').disabled=true; load();} else alert('Error');}
document.addEventListener('DOMContentLoaded', async()=>{await ensureSession(); const t=document.getElementById('t'); const c=document.getElementById('c'); t.addEventListener('input',()=>{c.textContent=t.value.length; const col=meterColor(t.value); setMeter(col); document.getElementById('note').classList.toggle('hidden',col!=='red')}); document.getElementById('post').onclick=post; setMeter('green'); load(); setInterval(load,2000);});
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def index(): return INDEX_HTML

@app.get("/sw.js", response_class=PlainTextResponse)
def sw(): return "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>self.clients.claim());"

# prime and run
if __name__=="__main__":
    hourly_tick()
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
