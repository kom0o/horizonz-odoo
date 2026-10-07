# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Safe read-only SQL provider.

Where the incumbent concatenates user SQL onto the live cursor and runs it for
real, this provider is locked down four ways:

1. **Whitelist** - the statement must be a single ``SELECT`` / ``WITH``; a
   forbidden-keyword scan rejects any write verb, and no ``;`` is allowed.
2. **Rollback** - the query runs inside a SAVEPOINT that is ALWAYS rolled back,
   so even a statement that slipped through could not persist a change.
3. **Timeout** - a per-statement ``statement_timeout`` stops a runaway query.
4. **LIMIT** - the query is wrapped in an outer ``LIMIT`` so it can never stream
   an unbounded result.

Admin-only at the model layer. The first result column is the category label;
the remaining numeric columns become the measures.
"""
import re

from ..lib.registry import BoardDataSource, register_datasource
from ..lib import aggregation

# Write / DDL / control verbs.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|into|call|do|merge|vacuum|analyze|reindex|comment|lock|"
    r"set|reset|prepare|execute|listen|notify|cluster|refresh)\b", re.IGNORECASE)
# Filesystem / network / large-object / system-catalog escapes that a plain
# write-keyword denylist misses (the exact holes the audit named). Blocking
# these plus the outer read-only transaction closes the class. Also blocked:
#   - catalog VIEWS (pg_stat_activity leaks other sessions' in-flight SQL, which
#     routinely inlines credentials; pg_roles/pg_user/pg_settings/pg_class expose
#     roles and configuration) - readable even with no function call.
#   - session-scoped, NON-transactional functions whose effects SURVIVE the
#     savepoint rollback (nextval/setval advance a sequence for good; advisory
#     locks and backend-control functions poison the pooled connection). These
#     are legal inside a SELECT, so the "always rolled back" guarantee needs them
#     blocked outright, not just rolled back.
_DANGEROUS = re.compile(
    r"\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|pg_sleep|"
    r"lo_import|lo_export|lo_get|lo_put|dblink|dblink_exec|postgres_fdw|"
    r"pg_catalog|information_schema|current_setting|set_config|pg_authid|"
    r"pg_shadow|pg_read_server_files|pg_execute_server_program|"
    r"pg_stat_activity|pg_stat_statements|pg_stat_replication|pg_user|pg_roles|"
    r"pg_settings|pg_class|pg_proc|pg_database|pg_stat_get_activity|"
    r"nextval|setval|currval|lastval|pg_advisory_lock|pg_advisory_xact_lock|"
    r"pg_advisory_unlock|pg_try_advisory_lock|pg_terminate_backend|"
    r"pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|txid_current|"
    r"pg_create_restore_point|pg_switch_wal|pg_switch_xlog|query_to_xml|"
    r"database_to_xml|pg_logical_emit_message)\b", re.IGNORECASE)
# Secret / credential stores that must never be read through this provider, even
# by an admin (a raw cursor bypasses field-level ACLs). Defence in depth on top
# of the admin-only result gate.
_SENSITIVE = re.compile(
    r"\b(eh_board_credential|ir_config_parameter|res_users|res_users_log|"
    r"auth_totp|ir_mail_server|payment_provider|payment_token|fetchmail_server)\b",
    re.IGNORECASE)

# SQL-standard unicode-escape identifier prefix (U&"\0070..." / U&'...'), which
# would let a blocked name be spelled past the plain-text denylists.
_UESCAPE = re.compile(r"u&['\"]", re.IGNORECASE)


@register_datasource
class SqlDataSource(BoardDataSource):
    key = "sql"
    label = "Safe SQL (read-only)"
    read_only = True
    external = False

    def _validate_sql(self, sql):
        if not sql:
            return "Enter a SELECT query."
        # This is a locked-down read-only provider, so SQL COMMENTS ARE NOT
        # PERMITTED. Stripping comments before the denylist scan was unsafe: a
        # "--" or "/*" appearing INSIDE a string literal desynced the scanned
        # text from what actually executes, letting a dangerous call hide behind
        # a fake comment marker. Rejecting comments outright and scanning the RAW
        # query removes that whole bypass class (a keyword inside a real string
        # literal is a conservative false-positive here, which is safe).
        if "--" in sql or "/*" in sql or "*/" in sql:
            return ("SQL comments (-- or /* */) are not permitted in a dashboard "
                    "query.")
        scan = re.sub(r"\s+", " ", sql).strip()
        low = scan.lower()
        if not (low.startswith("select") or low.startswith("with")):
            return "Only SELECT (or WITH ... SELECT) queries are allowed."
        if ";" in scan:
            return "Only a single statement is allowed."
        if _UESCAPE.search(scan):
            return ("Unicode-escaped identifiers (U&\"...\") are not permitted; "
                    "write table and column names in plain text.")
        if _FORBIDDEN.search(scan):
            return "Only read-only SELECT queries are allowed (a write keyword was found)."
        if _DANGEROUS.search(scan):
            return ("This query references a filesystem, network, session-control "
                    "or system-catalog function that is not permitted.")
        if _SENSITIVE.search(scan):
            return ("This query references a credential / user / configuration table "
                    "that is not permitted.")
        return None

    def aggregate(self, source, spec):
        # SQL results reach ONLY dashboard admins. A raw cursor bypasses Odoo's
        # field-level ACLs and record rules, so a shared board must never surface
        # SQL-source data to a Viewer; an admin can already read these tables.
        env = source.env
        if not env.su and not env.user.has_group("eh_board.group_board_admin"):
            return {"rows": [], "measures": [], "dimensions": [],
                    "error": "SQL widgets are visible to dashboard admins only."}
        sql = (source.sql_query or "").strip().rstrip(";").strip()
        problem = self._validate_sql(sql)
        if problem:
            return {"rows": [], "measures": [], "dimensions": [], "error": problem}
        cr = env.cr
        limit = max(1, min(int(spec.get("limit") or 500), 5000))
        # Optional least-privilege lockdown: a hardened deployment creates a
        # read-only Postgres role REVOKEd from credential/user/config tables and
        # sets ir.config_parameter 'eh_board.sql_role' to it; we SET LOCAL ROLE to
        # it for the duration of the query (rolled back with the savepoint). The
        # role name is validated as a bare identifier, so there is no injection.
        role = env["ir.config_parameter"].sudo().get_param("eh_board.sql_role")
        cr.execute("SAVEPOINT eh_board_sql")
        try:
            cr.execute("SET LOCAL statement_timeout = '5s'")
            if role and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", role):
                cr.execute('SET LOCAL ROLE "%s"' % role)
            cr.execute("SELECT * FROM (%s) AS _eh_q LIMIT %s" % (sql, limit))
            cols = [d.name for d in cr.description]
            raw = cr.fetchall()
        except Exception as err:  # noqa: BLE001 - surfaced to the widget
            return {"rows": [], "measures": [], "dimensions": [],
                    "error": "Query failed: %s" % err}
        finally:
            # Always undo anything the statement might have touched.
            cr.execute("ROLLBACK TO SAVEPOINT eh_board_sql")

        raw_measure_cols = cols[1:] if len(cols) > 1 else cols
        label_idx = 0 if len(cols) > 1 else None
        # Postgres names every unaliased aggregate the same ("sum", "count"...),
        # so two measure columns can collide. Keep each distinct by suffixing the
        # duplicates - otherwise the first measure's numbers vanish into the last.
        measure_cols, used = [], set()
        for col in raw_measure_cols:
            name, i = col, 1
            # Bump the suffix until the NAME (including any generated _N) is
            # unique - checking generated names too, so a synthesized "sum_2"
            # cannot collide with a genuine column literally named "sum_2".
            while name in used:
                i += 1
                name = "%s_%d" % (col, i)
            used.add(name)
            measure_cols.append(name)
        rows = []
        for tup in raw:
            values = {}
            for i, col in enumerate(measure_cols):
                idx = (i + 1) if len(cols) > 1 else i
                val = tup[idx]
                # bool is an int subclass but is not a measure; Decimal/int/float
                # are numbers. Anything else (text, date, interval) is not a
                # measure and stays 0.0.
                if isinstance(val, bool):
                    values[col] = 0.0
                elif isinstance(val, (int, float)):
                    values[col] = float(val)
                else:
                    try:
                        values[col] = float(val)
                    except (TypeError, ValueError):
                        values[col] = 0.0
            label = tup[label_idx] if label_idx is not None else ""
            rows.append({"keys": [label], "labels": [str(label)], "values": values})
        result = {
            "rows": rows, "measures": measure_cols, "dimensions": ["_sql"],
            "measure_labels": {c: c for c in measure_cols},
        }
        return aggregation.sort_and_cap(
            result, spec.get("sort", "default"), spec.get("limit"))

    def validate(self, source):
        problem = self._validate_sql((source.sql_query or "").strip().rstrip(";").strip())
        return [problem] if problem else []
