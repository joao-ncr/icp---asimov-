-- Modelo de dados do MVP. JSON guardado como TEXT.
CREATE TABLE IF NOT EXISTS service (id TEXT PRIMARY KEY, name TEXT, stack TEXT, problems_solved TEXT, hypothesis_template TEXT);
CREATE TABLE IF NOT EXISTS case_study (id TEXT PRIMARY KEY, client TEXT, service_id TEXT REFERENCES service(id), problem TEXT,
  capabilities TEXT, verified INTEGER DEFAULT 0, source TEXT);
CREATE TABLE IF NOT EXISTS icp (id TEXT PRIMARY KEY, name TEXT, services TEXT, status TEXT, confidence REAL, definition TEXT);
CREATE TABLE IF NOT EXISTS search_run (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, config TEXT, metrics TEXT);
CREATE TABLE IF NOT EXISTS search_query (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER REFERENCES search_run(id),
  icp_id TEXT REFERENCES icp(id), query TEXT, rationale TEXT, results INTEGER DEFAULT 0, top20 INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS organization (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, name_norm TEXT, domain TEXT UNIQUE, cnpj TEXT UNIQUE,
  municipio TEXT, uf TEXT, porte TEXT, cnae TEXT, segment TEXT, source TEXT, status TEXT DEFAULT 'pending',
  known_status TEXT, known_detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS page (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER REFERENCES organization(id), url TEXT,
  status_code INTEGER, fetched_at TEXT, text TEXT, features TEXT, injection_flags INTEGER DEFAULT 0, UNIQUE(org_id, url));
CREATE TABLE IF NOT EXISTS company_profile (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER REFERENCES organization(id),
  run_id INTEGER REFERENCES search_run(id), facts TEXT, extractor_version TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS signal (code TEXT PRIMARY KEY, category TEXT, kind TEXT, source TEXT, strength REAL, observability TEXT,
  description TEXT, interpretation TEXT, services TEXT);
CREATE TABLE IF NOT EXISTS analysis (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER REFERENCES organization(id),
  run_id INTEGER REFERENCES search_run(id), status TEXT, reason TEXT, llm_backend TEXT, model TEXT, prompt_hash TEXT,
  weights_hash TEXT, result TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER REFERENCES analysis(id),
  org_id INTEGER REFERENCES organization(id), signal_code TEXT REFERENCES signal(code), claim TEXT,
  type TEXT CHECK(type IN ('fact','inference','hypothesis','absence_inference')), source_kind TEXT, source_url TEXT,
  source_text TEXT, confidence REAL, verified INTEGER);
CREATE TABLE IF NOT EXISTS opportunity (id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER REFERENCES analysis(id),
  service_id TEXT REFERENCES service(id), hypothesis TEXT, explanation TEXT, confidence REAL);
CREATE TABLE IF NOT EXISTS score (id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER REFERENCES analysis(id),
  service_id TEXT, value REAL, components TEXT);   -- service_id='FINAL' guarda o score geral; 'B1' o baseline de setor
CREATE TABLE IF NOT EXISTS human_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER REFERENCES organization(id),
  analysis_id INTEGER, quality TEXT, status TEXT, reason TEXT, author TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS known_lead (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, name_norm TEXT, domain TEXT, outcome TEXT,
  value REAL, funnel TEXT, loss_reason TEXT, loss_category TEXT, segment TEXT, is_person INTEGER DEFAULT 0, created_month TEXT);
CREATE INDEX IF NOT EXISTS ix_page_org ON page(org_id);
CREATE INDEX IF NOT EXISTS ix_analysis_org ON analysis(org_id);
CREATE INDEX IF NOT EXISTS ix_evidence_an ON evidence(analysis_id);
CREATE INDEX IF NOT EXISTS ix_score_an ON score(analysis_id);
