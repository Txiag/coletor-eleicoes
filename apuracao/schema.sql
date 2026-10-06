CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    base_url TEXT NOT NULL,
    cycle TEXT NOT NULL,
    poll INTEGER NOT NULL,
    phase TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    checked_at TEXT,
    status INTEGER,
    error TEXT,
    fetched_at TEXT,
    kind TEXT,
    phase TEXT
);
CREATE TABLE IF NOT EXISTS elections (
    dataset TEXT NOT NULL REFERENCES datasets(id),
    code INTEGER NOT NULL,
    name TEXT NOT NULL,
    round INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(dataset,code)
);
CREATE TABLE IF NOT EXISTS offices (
    dataset TEXT NOT NULL REFERENCES datasets(id),
    election INTEGER NOT NULL,
    coverage TEXT NOT NULL,
    code INTEGER NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY(dataset,election,coverage,code)
);
CREATE TABLE IF NOT EXISTS territories (
    source_url TEXT NOT NULL REFERENCES sources(url),
    uf TEXT NOT NULL,
    municipality TEXT NOT NULL DEFAULT '',
    zone TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    PRIMARY KEY(source_url,uf,municipality,zone)
);
CREATE TABLE IF NOT EXISTS candidates (
    dataset TEXT NOT NULL REFERENCES datasets(id),
    election INTEGER NOT NULL,
    office INTEGER NOT NULL,
    scope TEXT NOT NULL,
    number TEXT NOT NULL,
    tse_id TEXT,
    name TEXT NOT NULL,
    party TEXT NOT NULL,
    party_name TEXT NOT NULL,
    office_name TEXT NOT NULL,
    PRIMARY KEY(dataset,election,office,scope,number)
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    source_url TEXT NOT NULL REFERENCES sources(url),
    dataset TEXT NOT NULL REFERENCES datasets(id),
    election INTEGER NOT NULL,
    office INTEGER NOT NULL,
    scope TEXT NOT NULL,
    uf TEXT NOT NULL,
    municipality TEXT NOT NULL DEFAULT '',
    zone TEXT NOT NULL DEFAULT '',
    reported_election TEXT,
    reported_round TEXT,
    phase TEXT,
    kind TEXT,
    area TEXT,
    updated_at TEXT,
    available INTEGER NOT NULL,
    votes INTEGER,
    nominal_votes INTEGER,
    denominator INTEGER,
    totalized_sections INTEGER,
    total_sections INTEGER,
    parties_complete INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(dataset,election,office,uf,municipality,zone)
);
CREATE INDEX IF NOT EXISTS results_by_source ON results(source_url,dataset,office);
CREATE TABLE IF NOT EXISTS candidate_votes (
    result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
    candidate_number TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    votes INTEGER,
    percentage REAL,
    status TEXT,
    PRIMARY KEY(result_id,candidate_number)
);
CREATE TABLE IF NOT EXISTS party_votes (
    result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
    number TEXT NOT NULL,
    name TEXT NOT NULL,
    votes INTEGER,
    PRIMARY KEY(result_id,number)
);
CREATE TABLE IF NOT EXISTS vote_categories (
    result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    votes INTEGER NOT NULL,
    PRIMARY KEY(result_id,type)
);
CREATE TABLE IF NOT EXISTS collection_state (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL
);
