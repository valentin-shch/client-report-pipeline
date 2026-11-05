-- Runs once, when the local Postgres volume is first created. On Neon these
-- roles are made by hand with LOGIN and a password; the grants are the same.
CREATE DATABASE crp_test;
CREATE ROLE pipeline NOLOGIN;
CREATE ROLE app NOLOGIN;
