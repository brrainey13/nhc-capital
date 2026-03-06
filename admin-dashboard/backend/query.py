"""SQL validation and query execution helpers."""

import re

from fastapi import HTTPException

DANGEROUS_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)
# Block Postgres functions that can read files, execute commands, or escape the sandbox
BLOCKED_FUNCTIONS = re.compile(
    r"\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file"
    r"|dblink|dblink_exec|dblink_connect"
    r"|lo_import|lo_export|lo_get|lo_put"
    r"|pg_execute_server_program|pg_file_write"
    r"|current_setting\s*\(\s*'[^']*data_directory"
    r"|set_config)\b",
    re.IGNORECASE,
)
READ_ONLY_START_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

NUMERIC_PG_TYPES = {"integer", "bigint", "smallint", "numeric", "real", "double precision"}
DATE_PG_TYPES = {"date", "timestamp without time zone", "timestamp with time zone"}


def is_read_only_query(sql: str) -> bool:
    """Check if a SQL query is safe (read-only, single statement)."""
    stripped = sql.strip()
    if not stripped:
        return False
    without_trailing = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in without_trailing:
        return False
    if not READ_ONLY_START_PATTERN.match(without_trailing):
        return False
    if DANGEROUS_PATTERN.search(without_trailing):
        return False
    if BLOCKED_FUNCTIONS.search(without_trailing):
        return False
    return True


def validate_table_name(name: str, allowed_tables: set[str]) -> str:
    """Validate a table name exists in the allowed set."""
    if name not in allowed_tables:
        raise HTTPException(404, f"Table '{name}' not found")
    return name


def validate_column(col: str, valid_cols: set[str], param_name: str) -> str:
    """Validate a column name exists in the valid set."""
    if col not in valid_cols:
        raise HTTPException(400, f"Invalid {param_name}: '{col}'")
    return col


def build_operator_filter(
    col: str, operator: str, value, col_type: str, params: list, param_idx: int
) -> tuple[list[str], int]:
    """Build WHERE clause parts for an operator-based filter."""
    clauses: list[str] = []

    if col_type in NUMERIC_PG_TYPES:
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise HTTPException(400, f"'between' requires [min, max] for '{col}'")
            clauses.append(f'"{col}" >= ${param_idx}')
            params.append(value[0])
            param_idx += 1
            clauses.append(f'"{col}" <= ${param_idx}')
            params.append(value[1])
            param_idx += 1
        else:
            op_map = {"eq": "=", "ne": "!=", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
            sql_op = op_map.get(operator)
            if not sql_op:
                raise HTTPException(400, f"Invalid numeric operator: '{operator}'")
            clauses.append(f'"{col}" {sql_op} ${param_idx}')
            params.append(value)
            param_idx += 1

    elif col_type in DATE_PG_TYPES:
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise HTTPException(400, f"'between' requires [min, max] for '{col}'")
            clauses.append(f'"{col}" >= ${param_idx}')
            params.append(value[0])
            param_idx += 1
            clauses.append(f'"{col}" <= ${param_idx}')
            params.append(value[1])
            param_idx += 1
        elif operator == "before":
            clauses.append(f'"{col}" < ${param_idx}')
            params.append(value)
            param_idx += 1
        elif operator == "after":
            clauses.append(f'"{col}" > ${param_idx}')
            params.append(value)
            param_idx += 1
        else:
            raise HTTPException(400, f"Invalid date operator: '{operator}'")

    else:
        text_ops = {
            "contains": ("%{v}%", True),
            "equals": ("{v}", True),
            "starts_with": ("{v}%", True),
            "ends_with": ("%{v}", True),
        }
        if operator not in text_ops:
            raise HTTPException(400, f"Invalid text operator: '{operator}'")
        pattern, _ = text_ops[operator]
        clauses.append(f'CAST("{col}" AS TEXT) ILIKE ${param_idx}')
        params.append(pattern.replace("{v}", str(value)))
        param_idx += 1

    return clauses, param_idx
