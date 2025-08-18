-- Enable pg_cron extension (only needs to run once per database)
create extension if not exists "pg_cron";

-- Questions table
create table if not exists questions (
  id uuid primary key default gen_random_uuid(),
  hour_key text unique not null,
  text text not null,
  created_at timestamptz default now()
);

-- Answers table
create table if not exists answers (
  id uuid primary key default gen_random_uuid(),
  question_id uuid references questions(id) on delete cascade,
  stance text check (stance in ('for','against')) not null,
  body text not null,
  risk text,
  created_at timestamptz default now()
);

-- Purge answers older than ~1 hour
select cron.schedule(
  'purge_old_answers',
  '*/5 * * * *',
  $$delete from answers where created_at < now() - interval '1 hour'$$
);
