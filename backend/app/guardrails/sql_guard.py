"""PostgreSQL AST policy. Semantic correctness is deliberately a separate concern."""

import re
from dataclasses import dataclass
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


class SQLPolicyError(ValueError):
    pass


class SQLSyntaxError(ValueError):
    pass


SAFE_CASTS = frozenset(
    "BIGINT BOOLEAN CHAR DATE DECIMAL DOUBLE FLOAT INT INTERVAL NCHAR NVARCHAR SMALLINT TEXT TIME TIMETZ TIMESTAMP TIMESTAMPTZ VARCHAR".split()
)

SAFE_FUNCTIONS = frozenset(
    "AND OR NOT CASE IF SUM COUNT AVG MIN MAX COALESCE NULLIF ROUND ABS FLOOR CEIL CEILING LOWER UPPER LENGTH TRIM CAST EXTRACT TIMESTAMP_TRUNC DATE_TRUNC DATE_PART DATE_ADD DATE_SUB CURRENT_DATE CURRENT_TIMESTAMP LAG LEAD ROW_NUMBER RANK DENSE_RANK FIRST_VALUE LAST_VALUE POWER SQRT CONCAT SUBSTRING STR_POSITION GREATEST LEAST".split()
)


@dataclass(frozen=True)
class SafeQuery:
    sql: str
    display_limit: int
    probing: bool


def prepare_query(
    sql: str,
    parameters: dict,
    allowed_tables: frozenset[str],
    default_limit=50,
    max_limit=100,
) -> SafeQuery:
    try:
        trees = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise SQLSyntaxError("SQL syntax could not be parsed.") from exc
    if (
        len(trees) != 1
        or trees[0] is None
        or not isinstance(trees[0], (exp.Select, exp.Union, exp.Intersect, exp.Except))
    ):
        raise SQLPolicyError("Only one read-only SELECT query is allowed.")
    tree = trees[0]
    for node in tree.walk():
        if isinstance(
            node,
            (
                exp.DML,
                exp.DDL,
                exp.Into,
                exp.Lock,
                exp.Command,
                exp.Copy,
                exp.Transaction,
            ),
        ):
            raise SQLPolicyError("Database changes and locking statements are blocked.")
        if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            raise SQLPolicyError("Qualified function calls are blocked.")
        if isinstance(node, exp.Func):
            name = (
                node.name.upper()
                if isinstance(node, exp.Anonymous)
                else node.sql_name()
            )
            if name not in SAFE_FUNCTIONS:
                raise SQLPolicyError("This function is not approved for analytics.")
        if (
            isinstance(node, exp.DataType)
            and getattr(node.this, "value", str(node.this)).upper() not in SAFE_CASTS
        ):
            raise SQLPolicyError("This type cast is not approved for analytics.")
    for scope in traverse_scope(tree):
        for _, source in scope.sources.items():
            if isinstance(source, exp.Table):
                if (
                    source.catalog
                    or source.db not in {"", "public"}
                    or source.name not in allowed_tables
                ):
                    raise SQLPolicyError(
                        "Query references a table outside the business allowlist."
                    )
                if not isinstance(source.this, exp.Identifier):
                    raise SQLPolicyError("Table functions are blocked.")
                # Prevent temporary-schema shadowing of unqualified business names.
                source.set("db", exp.to_identifier("public"))
    # Also reject table-valued function syntax not represented as a normal source.
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SQLPolicyError("Table functions are blocked.")
    names = {p.name for p in tree.find_all(exp.Placeholder)}
    if any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n) for n in names
    ) or names != set(parameters):
        raise SQLPolicyError("Named SQL parameters do not match supplied values.")
    # PostgreSQL $1 or session variables are outside the named-binding contract.
    if tree.find(exp.Parameter):
        raise SQLPolicyError("Only named bound parameters are supported.")
    limit = tree.args.get("limit")
    if limit:
        value = limit.expression
        if (
            not isinstance(value, exp.Literal)
            or not value.is_int
            or int(value.this) < 1
        ):
            raise SQLPolicyError("LIMIT must be a positive integer literal.")
        requested = int(value.this)
    else:
        requested = default_limit
    display = requested if requested <= max_limit else default_limit
    probing = not limit or requested > display
    bounded = tree.limit(display + 1 if probing else display)
    rendered = bounded.sql(dialect="postgres")
    for name in names:
        rendered = rendered.replace(f"%({name})s", ":" + name)
    return SafeQuery(rendered, display, probing)
