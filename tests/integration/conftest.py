"""Explicitly isolated PostgreSQL infrastructure for integration acceptance."""

import os

import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict

from regulated_ai.adapters import PostgresDatabase


@pytest.fixture(scope="session")
def database() -> PostgresDatabase:
    url = os.environ.get("REGULAAI_TEST_POSTGRES_URL")
    if not url:
        if os.environ.get("REGULAAI_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail("Required isolated PostgreSQL integration database is not configured")
        pytest.skip("REGULAAI_TEST_POSTGRES_URL is not configured")
    try:
        database_name = str(conninfo_to_dict(url).get("dbname") or "")
    except Exception:
        pytest.fail("Isolated PostgreSQL test configuration is invalid", pytrace=False)
    if not database_name.endswith("_test"):
        pytest.fail("Integration database name must end with _test", pytrace=False)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("REGULAAI_DATABASE_URL", url)
        command.upgrade(Config("alembic.ini"), "head")
    configured = PostgresDatabase(url)
    configured.verify_schema()
    return configured
