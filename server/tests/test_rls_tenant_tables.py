"""WS2 — guard that TENANT_TABLES exactly matches the model surface.

Dialect-agnostic (no DB needed). Catches the silent-leak failure mode: a new
model with a ``user_id`` column that nobody added to TENANT_TABLES would never
get an RLS policy. This test fails the moment that happens.
"""
from server.src.db.models import Base
from server.src.db.rls import RLS_EXCLUDED_CREDENTIAL_TABLES, TENANT_TABLES


def _tables_with_user_id() -> set[str]:
    return {
        name
        for name, tbl in Base.metadata.tables.items()
        if "user_id" in tbl.columns
    }


def test_every_tenant_table_exists_in_metadata():
    for name in TENANT_TABLES:
        assert name in Base.metadata.tables, f"{name} is not a real table"


def test_tenant_tables_has_no_duplicates():
    assert len(TENANT_TABLES) == len(set(TENANT_TABLES))


def test_tenant_tables_matches_user_id_columns_exactly():
    """Every table carrying user_id is either covered by RLS or explicitly excluded
    as a pre-auth credential table — nothing falls through the cracks."""
    expected = _tables_with_user_id() - RLS_EXCLUDED_CREDENTIAL_TABLES
    assert set(TENANT_TABLES) == expected


def test_excluded_credential_tables_are_real_but_unpoliced():
    for name in RLS_EXCLUDED_CREDENTIAL_TABLES:
        assert name in Base.metadata.tables
        assert "user_id" in Base.metadata.tables[name].columns
        assert name not in TENANT_TABLES


def test_denormalized_children_are_covered():
    for child in (
        "expenses",
        "income",
        "rule_executions",
        "liability_adjustments",
        "import_rows",
        "campaign_progress",
        "earmarks",
    ):
        assert child in TENANT_TABLES
        assert "user_id" in Base.metadata.tables[child].columns
