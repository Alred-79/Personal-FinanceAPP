"""Custom SQLAlchemy column types shared across the models.

``JSONStr`` is the WS1 bridge type: it stores JSON as a native ``JSONB`` column
on Postgres (queryable, validated, indexable) while keeping the Python value a
serialized JSON *string* — which is the contract the whole app relies on
(``json.dumps`` on write, ``json.loads(col or "{}")`` on read across ~30 call
sites). A plain ``String().with_variant(JSONB, "postgresql")`` would NOT do this:
JSONB's own bind/result processors double-encode the already-serialized string on
write and hand back a parsed ``dict`` on read, breaking every ``json.loads``.

On SQLite ``JSONStr`` is a pure no-op (``TEXT`` + string passthrough), so the
default test suite and dev DB are completely unaffected.
"""

import json

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Text, TypeDecorator


class JSONStr(TypeDecorator):
    """JSONB on Postgres, TEXT elsewhere — Python value stays a JSON string."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        # Emit JSONB DDL on Postgres, TEXT everywhere else.
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        # App hands us a serialized JSON string. On PG, parse it to a Python
        # object so the underlying JSONB impl serializes exactly once (no
        # double-encoding). Tolerate an already-parsed value defensively.
        if value is None:
            return None
        if dialect.name == "postgresql":
            return json.loads(value) if isinstance(value, str) else value
        return value

    def process_result_value(self, value, dialect):
        # On PG the JSONB impl returns a parsed dict/list; re-serialize so the app
        # still receives the JSON string it expects and json.loads(...) works.
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, str) else json.dumps(value)
        return value
