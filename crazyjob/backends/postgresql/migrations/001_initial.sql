-- CrazyJob — Initial Schema Migration
-- Creates all cj_* tables, enums, and indexes.

-- Job status enum
DO $$ BEGIN
    CREATE TYPE cj_job_status AS ENUM (
        'enqueued', 'active', 'completed', 'failed', 'dead', 'scheduled', 'retrying'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Worker status enum
DO $$ BEGIN
    CREATE TYPE cj_worker_status AS ENUM ('idle', 'busy', 'stopped');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Primary jobs table
CREATE TABLE IF NOT EXISTS cj_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    queue           VARCHAR(255) NOT NULL DEFAULT 'default',
    class_path      VARCHAR(500) NOT NULL,
    args            JSONB        NOT NULL DEFAULT '[]',
    kwargs          JSONB        NOT NULL DEFAULT '{}',
    status          cj_job_status NOT NULL DEFAULT 'enqueued',
    priority        INTEGER      NOT NULL DEFAULT 50,

    -- Queue poisoning protection: both columns are NOT NULL.
    -- max_attempts has a CHECK constraint — zero is forbidden.
    -- A job with max_attempts=0 would loop forever on a buggy payload.
    attempts        INTEGER      NOT NULL DEFAULT 0,
    max_attempts    INTEGER      NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),

    run_at          TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    error           TEXT,
    worker_id       VARCHAR(500),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Indexes for worker fetch query performance
CREATE INDEX IF NOT EXISTS idx_cj_jobs_fetch
    ON cj_jobs (priority ASC, created_at ASC)
    WHERE status IN ('enqueued', 'retrying');

CREATE INDEX IF NOT EXISTS idx_cj_jobs_queue_status
    ON cj_jobs (queue, status);

CREATE INDEX IF NOT EXISTS idx_cj_jobs_run_at
    ON cj_jobs (run_at)
    WHERE run_at IS NOT NULL AND status IN ('enqueued', 'retrying', 'scheduled');

-- Worker registry
CREATE TABLE IF NOT EXISTS cj_workers (
    id              VARCHAR(500)      PRIMARY KEY,
    queues          TEXT[]            NOT NULL,
    concurrency     INTEGER           NOT NULL DEFAULT 1,
    status          cj_worker_status  NOT NULL DEFAULT 'idle',
    current_job_id  UUID REFERENCES cj_jobs(id) ON DELETE SET NULL,
    started_at      TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
    last_beat_at    TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

-- Dead letters
CREATE TABLE IF NOT EXISTS cj_dead_letters (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    original_job    JSONB       NOT NULL,
    reason          TEXT        NOT NULL,
    killed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resurrected_at  TIMESTAMPTZ
);

-- Recurring cron schedules
CREATE TABLE IF NOT EXISTS cj_schedules (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL UNIQUE,
    cron            VARCHAR(100) NOT NULL,
    class_path      VARCHAR(500) NOT NULL,
    args            JSONB        NOT NULL DEFAULT '[]',
    kwargs          JSONB        NOT NULL DEFAULT '{}',
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Queue pauses
CREATE TABLE IF NOT EXISTS cj_queue_pauses (
    queue           VARCHAR(255) PRIMARY KEY,
    paused_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    paused_by       VARCHAR(255)
);
