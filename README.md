# AgorHour

Ephemeral hourly debates. Answers are moderated and data is auto-purged.

## 1) Environment
Set these environment variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE`
- `OPENAI_API_KEY`
- `SESSION_SECRET`

(Optional browser key if you add a separate frontend build):
- `SUPABASE_ANON_KEY`

## 2) Supabase SQL
Run [`sql/setup.sql`](sql/setup.sql) in the Supabase SQL editor. It creates the tables and a `pg_cron` job to purge answers older than an hour.

## 3) Install & run
```bash
cd backend
npm install
npm start
```
The API runs on `http://localhost:3000`.

## 4) Endpoints
- `GET /api/question` – fetch current hour question (auto-creates a default if missing)
- `POST /api/question { text }` – set/override the current question
- `POST /api/answer { question_id, stance, body, risk? }` – add answer (moderated)
- `GET /api/answers` – list answers for current hour
- `GET /ping` – health check

Static assets in [`public/`](public) can be deployed with the backend (see `vercel.json`).

## 5) Notes
- OpenAI Moderation model: `omni-moderation-latest`
- Purge is handled in-database by `pg_cron` (see SQL file): answers older than ~1 hour removed.
- Do not expose the service role key to the browser.

## 6) License
MIT
