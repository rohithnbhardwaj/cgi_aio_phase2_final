'SQL'
-- create some sample tables
CREATE TABLE IF NOT EXISTS users (
  id serial PRIMARY KEY,
  username text NOT NULL,
  email text,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams (
  id serial PRIMARY KEY,
  name text NOT NULL,
  description text
);

CREATE TABLE IF NOT EXISTS projects (
  id serial PRIMARY KEY,
  team_id integer REFERENCES teams(id),
  name text NOT NULL,
  status text DEFAULT 'planning'
);

CREATE TABLE IF NOT EXISTS tasks (
  id serial PRIMARY KEY,
  project_id integer REFERENCES projects(id),
  title text NOT NULL,
  done boolean DEFAULT false,
  due_date date
);

CREATE TABLE IF NOT EXISTS events (
  id serial PRIMARY KEY,
  title text NOT NULL,
  start_ts timestamptz,
  end_ts timestamptz
);

CREATE TABLE IF NOT EXISTS products (
  id serial PRIMARY KEY,
  sku text UNIQUE,
  name text,
  price numeric(10,2)
);

CREATE TABLE IF NOT EXISTS orders (
  id serial PRIMARY KEY,
  user_id integer REFERENCES users(id),
  order_date timestamptz DEFAULT now(),
  total numeric(10,2)
);

CREATE TABLE IF NOT EXISTS order_items (
  id serial PRIMARY KEY,
  order_id integer REFERENCES orders(id),
  product_id integer REFERENCES products(id),
  qty integer,
  unit_price numeric(10,2)
);

-- insert a few sample rows (safe to re-run)
INSERT INTO teams (name, description) VALUES
  ('Platform','Platform infra'),
  ('AI','ML experiments')
ON CONFLICT DO NOTHING;

INSERT INTO users (username, email) VALUES
  ('alice','alice@example.com'),
  ('bob','bob@example.com')
ON CONFLICT DO NOTHING;

INSERT INTO products (sku, name, price) VALUES
  ('SKU-001','Widget', 9.99),
  ('SKU-002','Gadget', 19.99)
ON CONFLICT DO NOTHING;

INSERT INTO orders (user_id, total) VALUES
  ((SELECT id FROM users WHERE username='alice' LIMIT 1), 29.98)
ON CONFLICT DO NOTHING;

INSERT INTO order_items (order_id, product_id, qty, unit_price) VALUES
  ((SELECT id FROM orders LIMIT 1), (SELECT id FROM products WHERE sku='SKU-001' LIMIT 1), 1, 9.99)
ON CONFLICT DO NOTHING;

-- show tables and schema summary
\dt
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='public'
ORDER BY table_name, ordinal_position;
SQL"