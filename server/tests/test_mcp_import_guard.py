"""CI import guard for the MCP boundary.

Scans every .py file under server/src/mcp/ except vault.py and fails if any
module imports from server.src.db, db.models, or SessionLocal.

vault.py is the *only* permitted entry point to the DB from the MCP side.
Keeping all other MCP modules DB-free makes the boundary enforceable, not
aspirational.

The final test (test_guard_bites_on_planted_violation) proves the scanner
actually catches a violation by parsing a string with a forbidden import.
"""

import ast
import pathlib
import textwrap

# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

_FORBIDDEN_ABSOLUTE = (
    "server.src.db",
    "server.src.db.models",
    "server.src.db.session",
)
_FORBIDDEN_NAMES = {"SessionLocal", "Base"}


def _has_forbidden_import(source: str) -> bool:
    """Return True if *source* contains an import that violates the boundary."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Absolute: import server.src.db[.*]
                if any(
                    alias.name == m or alias.name.startswith(m + ".")
                    for m in _FORBIDDEN_ABSOLUTE
                ):
                    return True
                if alias.name in _FORBIDDEN_NAMES:
                    return True

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Absolute: from server.src.db[.*] import ...
            if any(
                module == m or module.startswith(m + ".")
                for m in _FORBIDDEN_ABSOLUTE
            ):
                return True
            # Relative: from ..db[.*] import ... (from mcp/, level≥1, module starts with "db")
            if node.level >= 1 and (module == "db" or module.startswith("db.")):
                return True
            # Any import that names SessionLocal or Base directly
            for alias in node.names:
                if alias.name in _FORBIDDEN_NAMES:
                    return True

    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_MCP_SRC = (
    pathlib.Path(__file__).parent.parent / "src" / "mcp"
)


def _non_vault_modules():
    return [
        p for p in _MCP_SRC.glob("*.py")
        if p.name != "vault.py" and not p.name.startswith("__")
    ]


class TestImportGuard:
    def test_no_violations_in_real_mcp_tree(self):
        """All non-vault mcp/ modules must be DB-free."""
        violations = []
        for path in _non_vault_modules():
            source = path.read_text()
            if _has_forbidden_import(source):
                violations.append(path.name)
        assert violations == [], (
            f"These mcp/ modules import the DB directly (only vault.py may): {violations}"
        )

    def test_vault_itself_is_excluded(self):
        """vault.py must be excluded from the scan (it is the permitted importer)."""
        scanned = {p.name for p in _non_vault_modules()}
        assert "vault.py" not in scanned

    # ── Prove the scanner bites ──────────────────────────────────────────

    def test_guard_catches_absolute_import(self):
        bad = "from server.src.db.models import Expense"
        assert _has_forbidden_import(bad) is True

    def test_guard_catches_sessionlocal_from_session(self):
        bad = "from server.src.db.session import SessionLocal"
        assert _has_forbidden_import(bad) is True

    def test_guard_catches_relative_db_import(self):
        bad = "from ..db.models import Account"
        assert _has_forbidden_import(bad) is True

    def test_guard_catches_plain_sessionlocal_name(self):
        bad = "from ..db.session import SessionLocal"
        assert _has_forbidden_import(bad) is True

    def test_guard_passes_clean_module(self):
        clean = textwrap.dedent("""\
            import json
            from server.src.mcp.policy import PolicyError
            from server.src.mcp.principal import Principal
        """)
        assert _has_forbidden_import(clean) is False

    def test_guard_passes_audit_module(self):
        """audit.py itself must be clean (it has no DB imports)."""
        audit_path = _MCP_SRC / "audit.py"
        assert not _has_forbidden_import(audit_path.read_text())

    def test_guard_passes_policy_module(self):
        policy_path = _MCP_SRC / "policy.py"
        assert not _has_forbidden_import(policy_path.read_text())

    def test_guard_passes_principal_module(self):
        principal_path = _MCP_SRC / "principal.py"
        assert not _has_forbidden_import(principal_path.read_text())

    def test_guard_bites_on_planted_violation(self):
        """
        Prove the guard fails when a forbidden import is present — the key
        self-validation required by the trust gate.

        We parse a synthesised source string (no filesystem writes needed).
        """
        planted = textwrap.dedent("""\
            # Hypothetical mcp/evil.py that bypasses the vault
            from server.src.db.session import SessionLocal
            from server.src.db.models import Account

            def sneak(user_id):
                db = SessionLocal()
                return db.execute('SELECT * FROM accounts').fetchall()
        """)
        assert _has_forbidden_import(planted) is True, (
            "Guard did not catch planted ORM import — the boundary is unenforced!"
        )
