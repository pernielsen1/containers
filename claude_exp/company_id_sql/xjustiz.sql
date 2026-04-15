-- xjustiz.sql
-- Creates the xjustiz database and courts table.
-- Data is loaded by test_company_id.py from snippets_copy/XJustiz.json.

CREATE DATABASE IF NOT EXISTS xjustiz
--    CHARACTER SET utf8mb4
--    COLLATE utf8mb4_unicode_ci;

USE xjustiz;

DROP TABLE IF EXISTS courts;
CREATE TABLE courts (
    court_key  VARCHAR(200) NOT NULL COMMENT 'Cleaned court name (no spaces/dots/hyphens/parens)',
    court_code VARCHAR(10)  NOT NULL COMMENT 'XJustiz code e.g. R3101',
    court_name VARCHAR(200) NOT NULL COMMENT 'Original court name from XJustiz.json',
    PRIMARY KEY (court_key)
) ENGINE=InnoDB
--  DEFAULT CHARSET=utf8mb4
--  COLLATE=utf8mb4_unicode_ci;
