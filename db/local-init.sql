-- Runs once, when the local Postgres volume is first created. On Neon these
-- roles are made by hand with LOGIN and a password; the grants are the same.
CREATE DATABASE crp_test;
CREATE ROLE pipeline NOLOGIN;
-- The app logs in locally so its limited grants get exercised. Local only.
CREATE ROLE app LOGIN PASSWORD 'app-local-only';
