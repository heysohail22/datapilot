"""Allowlisted metadata only; no customer data sampling or auto-created tables."""

import threading
import time
from sqlalchemy import inspect


class SchemaCatalog:
    def __init__(self, engine, allowed_tables: frozenset[str], ttl=3600, notes=""):
        self.engine, self.allowed_tables, self.ttl, self.notes = (
            engine,
            allowed_tables,
            ttl,
            notes,
        )
        self._cached = None
        self._until = 0
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            if self._cached is not None and time.monotonic() < self._until:
                return self._cached
            inspector = inspect(self.engine)
            available = (
                set(inspector.get_table_names(schema="public")) & self.allowed_tables
            )
            tables = {}
            for table in sorted(available):
                columns = [
                    {"name": c["name"], "type": str(c["type"])}
                    for c in inspector.get_columns(table, schema="public")
                ]
                foreign_keys = [
                    f
                    for f in inspector.get_foreign_keys(table, schema="public")
                    if f["referred_table"] in available
                    and f.get("referred_schema") in {None, "public"}
                ]
                tables[table] = {
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                    "primary_key": inspector.get_pk_constraint(
                        table, schema="public"
                    ).get("constrained_columns", []),
                }
            if not tables:
                raise ValueError("No allowed business tables are available")
            self._cached = {"tables": tables, "mapping_and_grain_notes": self.notes}
            self._until = time.monotonic() + self.ttl
            return self._cached
