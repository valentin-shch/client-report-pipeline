import os

import pytest
from psycopg.conninfo import conninfo_to_dict


@pytest.fixture(scope="session")
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not conninfo_to_dict(url).get("dbname", "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a *_test database; these tests truncate it")
    from pipeline.db import connect, init_schema
    with connect(url) as conn:
        init_schema(conn)
    return url


@pytest.fixture
def db(pg_url):
    from psycopg import sql

    from pipeline.db import TABLES, connect
    with connect(pg_url) as conn:
        names = sql.SQL(", ").join(sql.Identifier(t) for t in TABLES)
        conn.execute(sql.SQL("truncate {}").format(names))
        conn.commit()
        yield conn
        conn.rollback()
