-- sample_inserts.sql
INSERT INTO products (sku, name, price)
VALUES ('SKU-001', 'Example Widget', 9.99)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO teams (name, description)
VALUES ('Engineering', 'Platform team')
ON CONFLICT (name) DO NOTHING;

INSERT INTO users (username, email)
VALUES ('alice', 'alice@example.com')
ON CONFLICT (username) DO NOTHING;

-- More Users
INSERT INTO users (username, email) VALUES 
('bob_tech', 'bob@company.com'),
('charlie_hr', 'charlie@humanresources.org'),
('dev_admin', 'admin@devops.io')
ON CONFLICT (username) DO NOTHING;

-- More Teams
INSERT INTO teams (name, description) VALUES 
('Marketing', 'Growth and social media'),
('Human Resources', 'People and Culture'),
('Sales', 'Direct enterprise sales')
ON CONFLICT (name) DO NOTHING;

-- More Products
INSERT INTO products (sku, name, price) VALUES 
('SKU-002', 'Professional Laptop', 1299.99),
('SKU-003', 'Wireless Mouse', 25.50),
('SKU-004', 'Ergonomic Chair', 350.00),
('SKU-005', 'Monitor Stand', 45.00)
ON CONFLICT (sku) DO NOTHING;