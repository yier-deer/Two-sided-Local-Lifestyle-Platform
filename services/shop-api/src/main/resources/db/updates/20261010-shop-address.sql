-- Additive, repeatable update for databases created before the address field.
ALTER TABLE shops ADD COLUMN IF NOT EXISTS address VARCHAR(255);
