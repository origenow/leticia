-- Letícia schema for Supabase.
-- Run this once in the Supabase SQL editor (or psql) for the project.
-- Idempotent: safe to re-run.

create schema if not exists leticia;

set search_path = leticia, public;

-- ---------------------------------------------------------------------------
-- leads: every WhatsApp number we've ever touched
-- ---------------------------------------------------------------------------
create table if not exists leticia.leads (
    id                bigserial primary key,
    phone             varchar(32) not null unique,
    display_name      varchar(200) not null default '',
    source            varchar(64)  not null default '',
    metadata          jsonb        not null default '{}'::jsonb,
    autonomy_enabled  boolean      not null default true,
    created_at        timestamptz  not null default now(),
    updated_at        timestamptz  not null default now()
);

create index if not exists leads_created_at_idx on leticia.leads(created_at desc);

-- ---------------------------------------------------------------------------
-- conversations: one per lead (we open a new one if the previous closed)
-- ---------------------------------------------------------------------------
create table if not exists leticia.conversations (
    id               bigserial primary key,
    lead_id          bigint not null references leticia.leads(id) on delete cascade,
    status           varchar(20) not null default 'active'
                       check (status in ('active','paused','escalated','closed')),
    last_message_at  timestamptz,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists conversations_lead_idx     on leticia.conversations(lead_id);
create index if not exists conversations_status_idx   on leticia.conversations(status);
create index if not exists conversations_last_msg_idx on leticia.conversations(last_message_at desc);

-- ---------------------------------------------------------------------------
-- messages: full transcript (inbound + outbound) — audit trail
-- ---------------------------------------------------------------------------
create table if not exists leticia.messages (
    id                    bigserial primary key,
    conversation_id       bigint not null references leticia.conversations(id) on delete cascade,
    direction             varchar(10) not null check (direction in ('inbound','outbound')),
    body                  text not null,
    evolution_message_id  varchar(128) not null default '',
    raw                   jsonb not null default '{}'::jsonb,
    created_at            timestamptz not null default now()
);

create index if not exists messages_conversation_created_idx
    on leticia.messages(conversation_id, created_at);

-- ---------------------------------------------------------------------------
-- opt_outs: hard block list. Letícia never speaks to these numbers again.
-- ---------------------------------------------------------------------------
create table if not exists leticia.opt_outs (
    id          bigserial primary key,
    phone       varchar(32) not null unique,
    reason      varchar(200) not null default '',
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- escalations: triggered by alert words (Procon, advogado etc.)
-- ---------------------------------------------------------------------------
create table if not exists leticia.escalations (
    id          bigserial primary key,
    lead_id     bigint not null references leticia.leads(id) on delete cascade,
    trigger     varchar(64) not null,
    context     text not null default '',
    resolved    boolean not null default false,
    created_at  timestamptz not null default now()
);

create index if not exists escalations_lead_idx     on leticia.escalations(lead_id);
create index if not exists escalations_resolved_idx on leticia.escalations(resolved);

-- ---------------------------------------------------------------------------
-- command_log: who ran what slash-command in #leticia-teste
-- ---------------------------------------------------------------------------
create table if not exists leticia.command_log (
    id              bigserial primary key,
    slack_user_id   varchar(32) not null,
    slack_user_name varchar(128) not null default '',
    command         varchar(64) not null,
    args            text not null default '',
    result          text not null default '',
    created_at      timestamptz not null default now()
);

create index if not exists command_log_user_idx       on leticia.command_log(slack_user_id);
create index if not exists command_log_created_at_idx on leticia.command_log(created_at desc);

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------
create or replace function leticia.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_leads_updated_at on leticia.leads;
create trigger trg_leads_updated_at
    before update on leticia.leads
    for each row execute function leticia.set_updated_at();

drop trigger if exists trg_conversations_updated_at on leticia.conversations;
create trigger trg_conversations_updated_at
    before update on leticia.conversations
    for each row execute function leticia.set_updated_at();

-- ---------------------------------------------------------------------------
-- RLS (Row Level Security) — service role bypasses RLS, so the Django app
-- using DATABASE_URL with the service role connection works as-is. We still
-- enable RLS here in case you wire up anon/auth clients later.
-- ---------------------------------------------------------------------------
alter table leticia.leads         enable row level security;
alter table leticia.conversations enable row level security;
alter table leticia.messages      enable row level security;
alter table leticia.opt_outs      enable row level security;
alter table leticia.escalations   enable row level security;
alter table leticia.command_log   enable row level security;

-- No policies created on purpose: only service_role can read/write for now.
-- Add policies later when you have human users authenticating via Supabase.
