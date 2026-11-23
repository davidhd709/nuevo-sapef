-- Se ejecuta una sola vez, al crear la base por primera vez.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- búsqueda por texto aproximada (solicitantes, direcciones)
CREATE EXTENSION IF NOT EXISTS unaccent;  -- búsquedas sin tildes
