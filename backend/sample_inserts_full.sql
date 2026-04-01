-- backend/sample_inserts_full.sql
-- Idempotent seed data for demo (safe to re-run)
-- Goal: 7–10+ rows per table for better demo UX

-- =========================
-- USERS (10)
-- =========================
INSERT INTO public.users (username, email) VALUES
  ('alice', 'alice@example.com'),
  ('bob',   'bob@example.com'),
  ('carol', 'carol@example.com'),
  ('dave',  'dave@example.com'),
  ('erin',  'erin@example.com'),
  ('frank', 'frank@example.com'),
  ('grace', 'grace@example.com'),
  ('heidi', 'heidi@example.com'),
  ('ivan',  'ivan@example.com'),
  ('judy',  'judy@example.com')
ON CONFLICT (username) DO NOTHING;


-- =========================
-- TEAMS (10)
-- =========================
INSERT INTO public.teams (name, description) VALUES
  ('Engineering', 'Platform team'),
  ('Platform',    'Platform infra'),
  ('AI',          'ML experiments'),
  ('Support',     'IT support'),
  ('DevOps',      'CI/CD and runtime operations'),
  ('Security',    'Security engineering and governance'),
  ('HR',          'People operations and HR'),
  ('Finance',     'Finance operations and reporting'),
  ('PMO',         'Project management office'),
  ('QA',          'Quality assurance and test engineering')
ON CONFLICT (name) DO NOTHING;


-- =========================
-- TEAM MEMBERS (15+)
-- PK on (team_id, user_id) so ON CONFLICT works
-- =========================
WITH members(team_name, username, role) AS (
  VALUES
    ('Engineering','alice','Lead'),
    ('Engineering','bob','Engineer'),
    ('Engineering','grace','Engineer'),
    ('Platform','dave','Lead'),
    ('Platform','heidi','Engineer'),
    ('AI','carol','Analyst'),
    ('AI','erin','ML Engineer'),
    ('AI','ivan','Data Scientist'),
    ('Support','frank','Analyst'),
    ('Support','judy','Coordinator'),
    ('DevOps','bob','Engineer'),
    ('DevOps','heidi','SRE'),
    ('Security','ivan','Security Engineer'),
    ('HR','judy','HR Specialist'),
    ('Finance','erin','Analyst'),
    ('PMO','alice','Sponsor'),
    ('QA','frank','Tester')
)
INSERT INTO public.team_members (team_id, user_id, role)
SELECT t.id, u.id, m.role
FROM members m
JOIN public.teams t ON t.name = m.team_name
JOIN public.users u ON u.username = m.username
ON CONFLICT (team_id, user_id) DO UPDATE SET role = EXCLUDED.role;


-- =========================
-- PRODUCTS (10)
-- =========================
INSERT INTO public.products (sku, name, price) VALUES
  ('SKU-001', 'Widget', 9.99),
  ('SKU-002', 'Gadget', 19.99),
  ('SKU-003', 'Doohickey', 4.50),
  ('SKU-004', 'Pro Widget', 29.99),
  ('SKU-005', 'Widget XL', 14.99),
  ('SKU-006', 'Gizmo', 7.25),
  ('SKU-007', 'Mega Gadget', 49.99),
  ('SKU-008', 'Adapter Pack', 6.99),
  ('SKU-009', 'Cable Kit', 5.49),
  ('SKU-010', 'Starter Bundle', 59.00)
ON CONFLICT (sku) DO NOTHING;


-- =========================
-- PROJECTS (10)
-- NOTE: no unique constraint -> use NOT EXISTS by name
-- =========================
WITH proj(team_name, name, status) AS (
  VALUES
    ('Engineering', 'AIO Demo Platform', 'active'),
    ('AI',          'RAG Policy Assistant', 'active'),
    ('DevOps',      'CI/CD Pipeline Hardening', 'active'),
    ('Security',    'Security Baseline Rollout', 'active'),
    ('Platform',    'Developer Portal Improvements', 'paused'),
    ('QA',          'Regression Suite Expansion', 'active'),
    ('Support',     'IT Service Catalog Refresh', 'active'),
    ('HR',          'Onboarding Experience Upgrade', 'active'),
    ('Finance',     'Cost Optimization Dashboard', 'active'),
    ('PMO',         'Portfolio Governance Setup', 'completed')
)
INSERT INTO public.projects (team_id, name, status)
SELECT t.id, p.name, p.status
FROM proj p
JOIN public.teams t ON t.name = p.team_name
WHERE NOT EXISTS (
  SELECT 1 FROM public.projects x WHERE x.name = p.name
);


-- =========================
-- TASKS (20+)
-- Avoid duplicates by (project_id, title) via NOT EXISTS
-- due_offset_days is integer: CURRENT_DATE + offset
-- =========================
WITH task_seed(project_name, title, done, due_offset_days) AS (
  VALUES
    -- AIO Demo Platform
    ('AIO Demo Platform','Wire schema search UI', false, 3),
    ('AIO Demo Platform','Add golden query capture', false, 7),
    ('AIO Demo Platform','Improve routing heuristics (docs vs sql)', false, 5),
    ('AIO Demo Platform','Create demo seed dataset (10+ rows)', true, -2),

    -- RAG Policy Assistant
    ('RAG Policy Assistant','Ingest HR PDFs and docs', true, -1),
    ('RAG Policy Assistant','Add document upload panel in UI', true, -3),
    ('RAG Policy Assistant','Tune chunking size and overlap', false, 4),

    -- CI/CD Pipeline Hardening
    ('CI/CD Pipeline Hardening','Audit Bamboo agents configuration', false, 6),
    ('CI/CD Pipeline Hardening','Add build plan templates', false, 10),

    -- Security Baseline Rollout
    ('Security Baseline Rollout','Publish password reset SOP', true, -5),
    ('Security Baseline Rollout','Review VPN access controls', false, 8),

    -- Developer Portal Improvements
    ('Developer Portal Improvements','Improve navigation and search', false, 12),
    ('Developer Portal Improvements','Add FAQ / docs landing page', false, 14),

    -- Regression Suite Expansion
    ('Regression Suite Expansion','Add SQL guardrail tests', true, -7),
    ('Regression Suite Expansion','Add RAG retrieval quality tests', false, 9),

    -- IT Service Catalog Refresh
    ('IT Service Catalog Refresh','Update laptop replacement workflow', false, 11),
    ('IT Service Catalog Refresh','Add ticket priority matrix', true, -4),

    -- Onboarding Experience Upgrade
    ('Onboarding Experience Upgrade','Refresh onboarding checklist', true, -6),
    ('Onboarding Experience Upgrade','Add role-based onboarding paths', false, 15),

    -- Cost Optimization Dashboard
    ('Cost Optimization Dashboard','Define metrics and KPIs', true, -10),
    ('Cost Optimization Dashboard','Build MVP dashboard view', false, 16),

    -- Portfolio Governance Setup
    ('Portfolio Governance Setup','Finalize portfolio intake process', true, -20),
    ('Portfolio Governance Setup','Publish governance cadence', true, -18)
)
INSERT INTO public.tasks (project_id, title, done, due_date)
SELECT p.id, s.title, s.done, (CURRENT_DATE + s.due_offset_days)
FROM task_seed s
JOIN public.projects p ON p.name = s.project_name
WHERE NOT EXISTS (
  SELECT 1 FROM public.tasks t
  WHERE t.project_id = p.id AND t.title = s.title
);


-- =========================
-- TASK COMMENTS (12+)
-- Avoid duplicates by (task_id, body) via NOT EXISTS
-- =========================
WITH c(project_name, task_title, author_username, body) AS (
  VALUES
    ('AIO Demo Platform','Wire schema search UI','alice','Initial UI wiring done; ready for review.'),
    ('AIO Demo Platform','Add golden query capture','bob','Added feedback capture; next is auto-promotion thresholds.'),
    ('AIO Demo Platform','Improve routing heuristics (docs vs sql)','carol','Suggest adding bamboo/jira/doc keywords and 0-row fallback to RAG.'),
    ('AIO Demo Platform','Create demo seed dataset (10+ rows)','dave','Seed file expanded to improve demo realism.'),

    ('RAG Policy Assistant','Tune chunking size and overlap','erin','Chunk size 1200 / overlap 150 seems stable for PDFs.'),
    ('RAG Policy Assistant','Add document upload panel in UI','grace','Upload + ingest works; need better routing defaults.'),

    ('CI/CD Pipeline Hardening','Audit Bamboo agents configuration','heidi','Found agent configuration notes in uploaded Bamboo guide.'),
    ('CI/CD Pipeline Hardening','Add build plan templates','ivan','Add Node.js pipeline template and artifact retention defaults.'),

    ('Security Baseline Rollout','Review VPN access controls','ivan','Confirm MFA and least-privilege group access.'),

    ('Developer Portal Improvements','Improve navigation and search','bob','Add consistent button styling and reduce whitespace on wide screens.'),

    ('IT Service Catalog Refresh','Update laptop replacement workflow','frank','Updated steps; please validate approvals for high-cost replacements.'),

    ('Cost Optimization Dashboard','Build MVP dashboard view','judy','Draft mockups ready; waiting on metric definitions.')
)
INSERT INTO public.task_comments (task_id, author_id, body)
SELECT t.id, u.id, c.body
FROM c
JOIN public.projects p ON p.name = c.project_name
JOIN public.tasks t ON t.project_id = p.id AND t.title = c.task_title
JOIN public.users u ON u.username = c.author_username
WHERE NOT EXISTS (
  SELECT 1 FROM public.task_comments x WHERE x.task_id = t.id AND x.body = c.body
);


-- =========================
-- EVENTS (10)
-- Avoid duplicates by title via NOT EXISTS
-- Uses NOW() offsets so it always looks current in demos
-- =========================
WITH e(title, start_offset_days, duration_minutes, location, created_by_username) AS (
  VALUES
    ('Project Kickoff', 1, 60, 'Teams', 'alice'),
    ('Demo Dry Run', 2, 45, 'Conf Room A', 'bob'),
    ('Architecture Review', 3, 60, 'Conf Room B', 'dave'),
    ('RAG Quality Workshop', 4, 75, 'Teams', 'carol'),
    ('Security Baseline Sync', 5, 30, 'Teams', 'ivan'),
    ('Platform Standup', 1, 15, 'Teams', 'heidi'),
    ('DevOps CI/CD Deep Dive', 6, 60, 'Conf Room C', 'heidi'),
    ('Onboarding Process Review', 7, 45, 'Teams', 'judy'),
    ('Finance Metrics Review', 8, 45, 'Teams', 'erin'),
    ('Release Readiness', 9, 30, 'Conf Room A', 'grace')
)
INSERT INTO public.events (title, start_ts, end_ts, location, created_by)
SELECT
  e.title,
  NOW() + (e.start_offset_days || ' days')::interval,
  NOW() + (e.start_offset_days || ' days')::interval + (e.duration_minutes || ' minutes')::interval,
  e.location,
  u.id
FROM e
JOIN public.users u ON u.username = e.created_by_username
WHERE NOT EXISTS (
  SELECT 1 FROM public.events x WHERE x.title = e.title
);

-- End of seed file