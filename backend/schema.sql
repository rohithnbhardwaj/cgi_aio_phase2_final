-- schema.sql
-- sample schema (8 tables)

CREATE TABLE IF NOT EXISTS users (
  id serial PRIMARY KEY,
  username text NOT NULL UNIQUE,
  email text UNIQUE,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams (
  id serial PRIMARY KEY,
  name text NOT NULL UNIQUE,
  description text
);

CREATE TABLE IF NOT EXISTS projects (
  id serial PRIMARY KEY,
  team_id integer REFERENCES teams(id) ON DELETE SET NULL,
  name text NOT NULL,
  status text NOT NULL DEFAULT 'planning'
);

CREATE TABLE IF NOT EXISTS tasks (
  id serial PRIMARY KEY,
  project_id integer REFERENCES projects(id) ON DELETE CASCADE,
  title text NOT NULL,
  done boolean DEFAULT false,
  due_date date
);

CREATE TABLE IF NOT EXISTS events (
  id serial PRIMARY KEY,
  title text NOT NULL,
  start_ts timestamptz,
  end_ts timestamptz,
  location text,
  created_by integer REFERENCES users(id),
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
  id serial PRIMARY KEY,
  sku text NOT NULL UNIQUE,
  name text NOT NULL,
  price numeric(10,2) NOT NULL DEFAULT 0.00,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_members (
  team_id integer REFERENCES teams(id) ON DELETE CASCADE,
  user_id integer REFERENCES users(id) ON DELETE CASCADE,
  role text,
  PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS task_comments (
  id serial PRIMARY KEY,
  task_id integer REFERENCES tasks(id) ON DELETE CASCADE,
  author_id integer REFERENCES users(id) ON DELETE SET NULL,
  body text NOT NULL,
  created_at timestamptz DEFAULT now()
);
