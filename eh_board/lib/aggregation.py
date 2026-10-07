# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Database-side aggregation helpers.

Every number on a board is produced here through ``_read_group`` - the grouped
read is pushed to Postgres, never loaded into Python and summed in a loop. This
is the performance line the incumbents cross: one competitor ``search``es the
whole recordset and folds it with getattr loops (which dies on ledger-scale
models), and another still calls the deprecated ``read_group(lazy=False)``.

The module is deliberately model-agnostic: it takes a live recordset (already
scoped by the caller's record rules and company), a group spec, and a list of
measures, and returns normalised rows.
"""

import logging
from datetime import date, datetime

import odoo.release
from odoo import _
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

# Major Odoo version at runtime. The grouped-read API changed at 17, so a single
# source can serve 16-19 by dispatching here instead of forking the module.
_ODOO_MAJOR = int(str(odoo.release.version_info[0]))

# Absolute upper bound on rows a single grouped read may return, so a widget
# over a very high-cardinality dimension can never OOM the worker.
_SAFETY_CAP = 20000


def grouped_read(model, domain, groupby, aggregates, order=None, limit=None):
    """Version-agnostic grouped read returning ordered value tuples.

    Odoo 17+ has ``_read_group(domain, groupby, aggregates)``; Odoo 16 only has
    classic ``read_group(lazy=False)`` (list of dicts). Both are wrapped so every
    caller unpacks the same ``(group_val..., agg_val...)`` tuple, and the module
    stays a single source across the whole 16-19 matrix - no per-version fork."""
    _check_grouped_field_access(model, domain, groupby, aggregates, order)
    if _ODOO_MAJOR >= 17:
        return model._read_group(domain, groupby=groupby, aggregates=aggregates,
                                 order=order, limit=limit)
    return classic_read_group(model, domain, groupby, aggregates, order=order, limit=limit)


def _check_grouped_field_access(model, domain, groupby, aggregates, order=None):
    """Protect field-group restrictions consistently, including classic Odoo16.

    Structural field metadata may be read for configured widgets, but the
    viewer must still be allowed to use each actual data field in this query.
    No source recordset is elevated here or in the database read below.
    """
    context = model.env.context  # Translation helper uses the caller language.
    paths = {token.split(":", 1)[0] for token in list(groupby) + list(aggregates)
             if token != "__count"}
    if order:
        paths.update(term.strip().split()[0].split(":", 1)[0]
                     for term in order.split(",") if term.strip())
    for leaf in domain or []:
        if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and isinstance(leaf[0], str):
            paths.add(leaf[0])
    paths.discard("__count")
    definitions = {}
    for path in paths:
        target = model
        parts = path.split(".")
        for index, name in enumerate(parts):
            if target._name not in definitions:
                definitions[target._name] = target.fields_get(attributes=["type"])
            if name not in definitions[target._name]:
                raise AccessError(_("This dashboard uses a field you are not allowed to read."))
            if index < len(parts) - 1:
                field = target._fields[name]
                if not getattr(field, "comodel_name", None):
                    raise AccessError(_("This dashboard uses a field you are not allowed to read."))
                target = target.env[field.comodel_name]


def _parse_iso(value):
    """Parse an ISO date/datetime string into a real object; passthrough else."""
    if not isinstance(value, str):
        return value
    try:
        if " " in value or "T" in value:
            return datetime.fromisoformat(value.replace("T", " "))
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return value


def classic_read_group(model, domain, groupby, aggregates, order=None, limit=None):
    """Odoo 16 ``read_group`` adapter returning the 17+ tuple shape. Only ever
    called on 16 (the ``read_group`` reference below is inert on 17+)."""
    domain = domain or []
    groupby = list(groupby)
    aggregates = list(aggregates)
    # Degenerate group-by-primary-key: Odoo 16 read_group selects both
    # ``min(id) AS id`` and the group key ``id AS id``, so ORDER BY "id" is
    # ambiguous. Each group is one record, so resolve via a bounded search.
    if groupby == ["id"]:
        out = []
        for rec in model.search(domain, limit=limit):
            avals = []
            for tok in aggregates:
                if tok == "__count":
                    avals.append(1)
                else:
                    fname, _s, _v = tok.partition(":")
                    avals.append(rec[fname] if fname in rec._fields else 0)
            out.append((rec.id,) + tuple(avals))
        return out
    field_specs, alias_plan, counter = [], [], 0
    for tok in aggregates:
        if tok == "__count":
            alias_plan.append(("__count", None))
            continue
        fname, _sep, verb = tok.partition(":")
        verb = verb or "sum"
        counter += 1
        alias = "ehg_%d" % counter
        field_specs.append("%s:%s(%s)" % (alias, verb, fname))
        alias_plan.append((alias, tok))
    # A pure-count read must inject an explicit count so classic read_group does
    # not fall back to aggregating every stored numeric field.
    if not field_specs:
        field_specs = ["__eh_n:count(id)"]

    def _run(orderby):
        return model.read_group(
            domain, fields=field_specs, groupby=list(groupby),
            lazy=False, orderby=orderby or False, limit=limit)

    try:
        rows = _run(order)
    except Exception:  # noqa: BLE001 - an order term the classic API rejects
        rows = _run(False)

    tuples = []
    for row in rows:
        gvals = []
        for gb in groupby:
            rng = (row.get("__range") or {}).get(gb) if isinstance(row, dict) else None
            if isinstance(rng, dict) and rng.get("from"):
                gvals.append(_parse_iso(rng["from"]))
            else:
                gvals.append(row.get(gb, False))
        avals = []
        for alias, _tok in alias_plan:
            avals.append(row.get("__count", 0) if alias == "__count" else row.get(alias, 0))
        tuples.append(tuple(gvals) + tuple(avals))
    return tuples

# Aggregate verbs we accept on a measure -> the token _read_group understands.
# ``count`` maps to the special ``__count`` aggregate; everything else is
# expressed as ``field:verb``.
_AGG_VERBS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "count": "__count",
    "count_distinct": "count_distinct",
    # median has no _read_group token; callers fall back to a post pass.
    "bool_and": "bool_and",
    "bool_or": "bool_or",
}

# Date group granularities the module may emit via ``field:granularity``.
_DATE_GRANULARITIES = {
    "minute", "hour", "day", "week", "month", "quarter", "year",
    "month_number", "day_of_week", "day_of_month",
}

# TIME granularities _read_group accepts on Odoo 17+ (verified against
# odoo/orm/utils.py READ_GROUP_TIME_GRANULARITY): NO 'minute' - the finest real
# time bucket is 'hour'. NUMBER granularities (month_number, day_of_week ...)
# only exist from Odoo 18 (READ_GROUP_NUMBER_GRANULARITY); on 16/17 they raise.
# Fold every unsupported granularity to the nearest supported one on each version
# so a widget never silently degrades to 'month' with a mislabelled axis.
_NUMBER_GRANULARITIES = {"month_number", "day_of_week", "day_of_month"}
_NUMBER_FALLBACK = {"month_number": "month", "day_of_week": "day", "day_of_month": "day"}


def _safe_granularity(granularity):
    """Clamp a date granularity to one the running Odoo major actually supports.

    Verified against the on-disk framework: 'minute' is not a valid time bucket
    on any supported version, and number granularities land only in Odoo 18."""
    if not granularity:
        return granularity
    # 'minute' is never a real _read_group time bucket: fold to 'hour' (17+) or
    # 'day' (16), never let it become 'month' via an exception.
    if granularity == "minute":
        return "hour" if _ODOO_MAJOR >= 17 else "day"
    # NUMBER granularities exist from 18 only.
    if granularity in _NUMBER_GRANULARITIES and _ODOO_MAJOR < 18:
        return _NUMBER_FALLBACK.get(granularity, "month")
    # Odoo 16 classic read_group has no sub-day bucket.
    if _ODOO_MAJOR < 17 and granularity == "hour":
        return "day"
    return granularity


def measure_aggregate_token(field_name, verb):
    """Return the ``_read_group`` aggregate token for one measure.

    ``count`` becomes ``__count`` (field-independent); other verbs become
    ``field:verb``. Unknown verbs fall back to ``sum``.
    """
    verb = _AGG_VERBS.get(verb, "sum")
    if verb == "__count":
        return "__count"
    return "%s:%s" % (field_name, verb)


def groupby_token(field_name, granularity=None):
    """Return a ``_read_group`` groupby token, adding ``:granularity`` for dates."""
    if granularity and granularity in _DATE_GRANULARITIES:
        return "%s:%s" % (field_name, _safe_granularity(granularity))
    return field_name


def _label_for(value, field_def=None):
    """Human label for a raw group value coming back from ``_read_group``."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is False or value is None:
        return "Undefined"
    # Relational groups arrive as a recordset in the new API.
    if hasattr(value, "_name") and hasattr(value, "display_name"):
        return value.display_name or "Undefined"
    # Many2one may still surface as an ``(id, name)`` pair on older versions.
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return value[1] or "Undefined"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTHS_FULL = ("", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")


def _date_label(value, granularity):
    """Readable axis label for a date-bucket group (Jan 2025, Q1 2025, 2025...)."""
    if isinstance(value, (date, datetime)):
        y, m, d = value.year, value.month, value.day
        if granularity == "year":
            return "%d" % y
        if granularity == "quarter":
            return "Q%d %d" % ((m - 1) // 3 + 1, y)
        if granularity == "month":
            return "%s %d" % (_MONTHS[m], y)
        if granularity == "week":
            # ISO week-year, not the calendar year: a week straddling 1 Jan
            # belongs to the ISO year, so "W01 2025" never mislabels.
            iso = value.isocalendar()
            return "W%02d %d" % (iso[1], iso[0])
        if granularity == "day":
            return "%d %s %d" % (d, _MONTHS[m], y)
        if granularity == "hour":
            # A Date field grouped by hour comes back as a datetime.date with no
            # .hour; getattr keeps it from crashing (renders the day at 00:00).
            return "%d %s %02d:00" % (d, _MONTHS[m], getattr(value, "hour", 0))
        if granularity == "minute":
            return "%02d:%02d" % (getattr(value, "hour", 0), getattr(value, "minute", 0))
        return value.isoformat()
    # month_number / day_of_week arrive as ints (or numeric strings).
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return _label_for(value)
    if granularity == "month_number" and 1 <= iv <= 12:
        return _MONTHS_FULL[iv]
    if granularity == "day_of_week" and 0 <= iv <= 6:
        return _WEEKDAYS[iv]
    return str(iv)


def _group_key(value):
    """A hashable, JSON-safe key for a group value (for gap-fill / joins)."""
    if value is False or value is None:
        return None
    if hasattr(value, "_name") and hasattr(value, "id"):
        return value.id
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return value[0]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def sort_and_cap(result, sort="default", limit=None, group_others=False):
    """Sort normalised rows by value or label, then cap to ``limit``.

    Done after the grouped read so "top N by value" is exact (sort precedes the
    cut) without pushing brittle aggregate-order strings into ``_read_group``.
    When ``group_others`` is set, the rows past the cap are summed into a single
    trailing "Others" group rather than dropped, so the total stays honest.
    """
    rows = result.get("rows", [])
    keys = result.get("measures", [])
    primary = keys[0] if keys else None
    if sort == "value_desc" and primary:
        rows = sorted(rows, key=lambda r: r["values"].get(primary, 0), reverse=True)
    elif sort == "value_asc" and primary:
        rows = sorted(rows, key=lambda r: r["values"].get(primary, 0))
    elif sort == "label":
        rows = sorted(rows, key=lambda r: (str(r["labels"][0]) if r["labels"] else ""))
    if limit and len(rows) > limit:
        tail = rows[limit:]
        rows = rows[:limit]
        # An "Others" bucket is only mathematically honest for ADDITIVE measures
        # (sum / count). Summing per-group averages, mins, maxes or distinct
        # counts into one bucket is meaningless, so disable Others when any
        # measure is non-additive (the tail is dropped instead of faked).
        verbs = result.get("measure_verbs") or {}
        additive = all(verbs.get(k, "sum") in ("sum", "count") for k in keys)
        if group_others and tail and additive:
            merged = {k: 0.0 for k in keys}
            for r in tail:
                for k in keys:
                    merged[k] += r["values"].get(k, 0) or 0
            rows.append({
                "keys": ["__others__"],
                "labels": ["Others (%d)" % len(tail)],
                "values": merged,
                "is_others": True,
            })
    result["rows"] = rows
    return result


def cumulate(rows, measure_keys):
    """Turn each measure into a running total across the rows in order.

    Applied after sort so a "cumulative" line/bar climbs monotonically. Returns
    new row dicts; the originals are left untouched.
    """
    if not rows:
        return rows
    totals = {k: 0.0 for k in measure_keys}
    out = []
    for r in rows:
        vals = dict(r.get("values", {}))
        for k in measure_keys:
            totals[k] += vals.get(k, 0) or 0
            vals[k] = totals[k]
        out.append({**r, "values": vals})
    return out


def aggregate(model, domain, dimensions, measures, order=None, limit=None):
    """Run one grouped read and return normalised rows.

    :param model: a live recordset already scoped to the right company / rules.
    :param domain: search domain (list).
    :param dimensions: ordered list of ``{"field": name, "granularity": g|None}``.
        May be empty for a single-value KPI.
    :param measures: ordered list of ``{"key": k, "field": f|None, "verb": v}``.
    :param order: optional ``_read_group`` order string.
    :param limit: optional row cap.
    :returns: ``{"rows": [...], "measures": [...], "dimensions": [...]}`` where
        each row is ``{"keys": [...], "labels": [...], "values": {key: number}}``.
    """
    groupby = [groupby_token(d["field"], d.get("granularity")) for d in dimensions]
    agg_tokens, measure_meta = [], []
    for m in measures:
        verb = m.get("verb", "sum")
        if verb == "count" or not m.get("field"):
            token = "__count"
        else:
            token = measure_aggregate_token(m["field"], verb)
        agg_tokens.append(token)
        measure_meta.append({
            "key": m["key"], "token": token,
            "multiplier": m.get("multiplier", 1.0) or 1.0})

    # _read_group returns a list of tuples: the group values first (one per
    # groupby), then the aggregate values in order.
    # Never issue an unbounded grouped read: a missing cap defaults to a large
    # safety bound (exact top-N still happens in Python for anything under it).
    read_limit = limit if limit else _SAFETY_CAP
    try:
        raw = grouped_read(
            model, domain, groupby, agg_tokens, order=order, limit=read_limit)
    except (ValueError, KeyError) as err:
        # A fine granularity (minute/hour) asked of a plain Date field, or one an
        # older server rejects, raises here. Degrade every date bucket to 'month'
        # and retry once so the widget still renders rather than erroring out.
        degraded = [groupby_token(d["field"], "month" if d.get("granularity")
                    in _DATE_GRANULARITIES else d.get("granularity"))
                    for d in dimensions]
        if degraded == groupby:
            raise
        _logger.warning("eh_board.aggregate: granularity retry after %s", err)
        groupby = degraded
        raw = grouped_read(
            model, domain, groupby, agg_tokens, order=order, limit=read_limit)

    ndims = len(groupby)
    # Label with the EFFECTIVE (clamped) granularity, so a month_number that had
    # to degrade to a month bucket on Odoo 16/17 renders "Jan 2025" rather than a
    # raw ISO date from the month_number int path.
    grans = [_safe_granularity(d.get("granularity")) for d in dimensions]

    def _label(v, i):
        g = grans[i] if i < len(grans) else None
        return _date_label(v, g) if g else _label_for(v)

    rows = []
    for tup in raw:
        group_values = tup[:ndims]
        agg_values = tup[ndims:]
        values = {}
        for meta, val in zip(measure_meta, agg_values):
            v = 0.0 if val is None or val is False else val
            # Apply the measure's display scale (e.g. 0.001 to show thousands).
            values[meta["key"]] = v * meta["multiplier"]
        rows.append({
            "keys": [_group_key(v) for v in group_values],
            "labels": [_label(v, i) for i, v in enumerate(group_values)],
            "values": values,
        })
    return {
        "rows": rows,
        "measures": [m["key"] for m in measures],
        "dimensions": [d["field"] for d in dimensions],
        # Verb per measure, so downstream can tell additive (sum/count) from
        # non-additive (avg/min/max/count_distinct) aggregates.
        "measure_verbs": {m["key"]: m.get("verb", "sum") for m in measures},
    }


def fill_time_gaps(rows, granularity):
    """Fill missing periods in a single-dimension time series with zero rows.

    Only applies when the sole dimension is a date bucket; otherwise the rows
    are returned untouched. Keeps a line/area chart from drawing across holes.
    """
    if not rows or granularity not in {"day", "week", "month", "quarter", "year"}:
        return rows
    # Rows whose first key is an ISO date string; skip if not parseable. Rows that
    # are NOT stamped dates (notably the null-date "Undefined" group) must be
    # preserved, not dropped - dropping them silently undercounts the total.
    stamped, extras = [], []
    for r in rows:
        key = r["keys"][0] if r["keys"] else None
        if isinstance(key, str):
            try:
                stamped.append((datetime.fromisoformat(key), r))
                continue
            except ValueError:
                pass
        extras.append(r)
    if len(stamped) < 2:
        return rows
    stamped.sort(key=lambda p: p[0])
    step = _period_step(granularity)
    filled, cursor, idx = [], stamped[0][0], 0
    last = stamped[-1][0]
    measure_keys = list(rows[0]["values"].keys())
    guard = _SAFETY_CAP  # never expand into an unbounded number of zero rows
    while cursor <= last and guard > 0:
        guard -= 1
        if idx < len(stamped) and stamped[idx][0] == cursor:
            filled.append(stamped[idx][1])
            idx += 1
        else:
            filled.append({
                "keys": [cursor.date().isoformat()],
                "labels": [_date_label(cursor, granularity)],
                "values": {k: 0.0 for k in measure_keys},
            })
        cursor = step(cursor)
    # Re-append any non-date rows (e.g. the null-date "Undefined" group) so the
    # widget total still reconciles with the un-filled series.
    return filled + extras


def _period_step(granularity):
    """Return a function advancing a datetime by one bucket of ``granularity``."""
    if granularity == "day":
        return lambda d: _add_days(d, 1)
    if granularity == "week":
        return lambda d: _add_days(d, 7)
    if granularity == "month":
        return lambda d: _add_months(d, 1)
    if granularity == "quarter":
        return lambda d: _add_months(d, 3)
    return lambda d: _add_months(d, 12)


def _add_days(d, n):
    from datetime import timedelta
    return d + timedelta(days=n)


def _add_months(d, n):
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    return d.replace(year=year, month=month, day=1)
