-- CrazyJob — Initial Schema Migration (SQLite)
-- Creates all cj_* tables and indexes.

-- Primary jobs table
CREATE TABLE IF NOT EXISTS cj_jobs (
    id              TEXT PRIMARY KEY,
    queue           TEXT NOT NULL DEFAULT 'default',
    class_path      TEXT NOT NULL,
    args            TEXT NOT NULL DEFAULT '[]',
    kwargs          TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'enqueued'
                    CHECK(status IN ('enqueued','active','completed','failed','dead','scheduled','retrying')),
    priority        INTEGER NOT NULL DEFAULT 50,

    -- Queue poisoning protection: max_attempts >= 1
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),

    run_at          TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    failed_at       TEXT,
    error           TEXT,
    worker_id       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
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
    id              TEXT PRIMARY KEY,
    queues          TEXT NOT NULL,       -- JSON-encoded list
    concurrency     INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'idle'
                    CHECK(status IN ('idle', 'busy', 'stopped')),
    current_job_id  TEXT REFERENCES cj_jobs(id) ON DELETE SET NULL,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_beat_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dead letters
CREATE TABLE IF NOT EXISTS cj_dead_letters (
    id              TEXT PRIMARY KEY,
    original_job    TEXT NOT NULL,       -- JSON
    reason          TEXT NOT NULL,
    killed_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resurrected_at  TEXT
);

-- Recurring cron schedules
CREATE TABLE IF NOT EXISTS cj_schedules (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    cron            TEXT NOT NULL,
    class_path      TEXT NOT NULL,
    args            TEXT NOT NULL DEFAULT '[]',
    kwargs          TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_run_at     TEXT,
    next_run_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Queue pauses
CREATE TABLE IF NOT EXISTS cj_queue_pauses (
    queue           TEXT PRIMARY KEY,
    paused_at       TEXT NOT NULL DEFAULT (datetime('now')),
    paused_by       TEXT
);
