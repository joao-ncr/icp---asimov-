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
-- Base historica de prospeccao (planilha padronizada): contexto por empresa que o modelo consome.
-- LGPD: telefone, decisor e socios NAO sao importados (ver docs/SEGURANCA_LGPD.md).
CREATE TABLE IF NOT EXISTS lead_history (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER NOT NULL UNIQUE REFERENCES organization(id),
  source_id INTEGER, segment_label TEXT, capital_social REAL, digital_maturity TEXT, best_offer TEXT, suggested_service TEXT,
  identity_confidence TEXT, registration_alert TEXT, cnpj_suspect INTEGER DEFAULT 0, ticket_filter TEXT, ticket_reason TEXT,
  priority TEXT, tier TEXT, legacy_score REAL, legacy_components TEXT, commercial_status TEXT, loss_reason TEXT, imported_at TEXT);
CREATE INDEX IF NOT EXISTS ix_lead_history_service ON lead_history(suggested_service);
-- Uma unica rodada de analise por vez (vale entre abas e processos). Linha unica; heartbeat evita trava eterna apos crash.
CREATE TABLE IF NOT EXISTS run_lock (id INTEGER PRIMARY KEY CHECK (id = 1), owner TEXT, label TEXT, started_at TEXT, heartbeat_at TEXT);
-- Aprendizado a partir do feedback humano: cada linha e um ajuste auditavel (params = multiplicadores por sinal/segmento).
CREATE TABLE IF NOT EXISTS calibration (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, n_labels INTEGER,
  last_feedback_id INTEGER, active INTEGER DEFAULT 0, params TEXT);
-- Integracao Ploomes (somente leitura): vinculo empresa do CRM -> organizacao do Prospector (varias podem cair na mesma
-- organizacao pela deduplicacao) e trilha de auditoria de cada sincronizacao (quem disparou, contagens, cursor incremental).
CREATE TABLE IF NOT EXISTS ploomes_company (contact_id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organization(id),
  last_update TEXT, synced_at TEXT);
CREATE INDEX IF NOT EXISTS ix_ploomes_company_org ON ploomes_company(org_id);
CREATE TABLE IF NOT EXISTS ploomes_sync (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, status TEXT,
  full_sync INTEGER, triggered_by TEXT, cursor TEXT, report TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS ix_analysis_org_status ON analysis(org_id, status, id);
CREATE INDEX IF NOT EXISTS ix_score_an_svc ON score(analysis_id, service_id);
CREATE INDEX IF NOT EXISTS ix_feedback_org ON human_feedback(org_id, id);
-- Geracao de leads novos (dados abertos de CNPJ, filtrados por ICP): candidatos passam por aprovacao humana
-- antes de virar organizacao (ver app/discovery/generation.py e app/discovery/review.py).
CREATE TABLE IF NOT EXISTS discovery_generation (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
  status TEXT, triggered_by TEXT, filename TEXT, report TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS discovery_candidate (id INTEGER PRIMARY KEY AUTOINCREMENT,
  generation_id INTEGER REFERENCES discovery_generation(id), name TEXT, name_norm TEXT, cnpj TEXT, cnae TEXT, uf TEXT,
  municipio TEXT, porte TEXT, segment TEXT, icp_id TEXT, rationale TEXT, status TEXT DEFAULT 'pending',
  org_id INTEGER REFERENCES organization(id), decided_by TEXT, decided_at TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_discovery_candidate_status ON discovery_candidate(status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_discovery_candidate_cnpj ON discovery_candidate(cnpj) WHERE cnpj IS NOT NULL;
