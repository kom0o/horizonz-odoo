# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The ORM datasource - the only provider the free engine needs.

It aggregates a single Odoo model with ``_read_group`` **as the current user**,
so record rules and multi-company scoping are always enforced. There is no
``apply_ir_rules=False`` escape hatch here (a hole a competing free module ships
by default). Join / SQL / external providers register alongside this one from
their own files without touching this code.
"""

import logging

from ..lib.registry import BoardDataSource, register_datasource
from ..lib import aggregation

_logger = logging.getLogger(__name__)


@register_datasource
class OrmDataSource(BoardDataSource):
    key = "orm"
    label = "Odoo model"
    read_only = True
    external = False

    def aggregate(self, source, spec):
        model_name = spec.get("model") or source.model_name
        if not model_name or model_name not in source.env:
            return {"rows": [], "measures": spec.get("measure_keys", []),
                    "dimensions": [], "error": "Unknown model %r" % model_name}
        # Current-user recordset: record rules + company scope applied by the ORM.
        model = source.env[model_name]
        ctx_company = spec.get("company_ids")
        if ctx_company:
            model = model.with_context(allowed_company_ids=ctx_company)
        # Opt-in: include archived (inactive) records. Record rules still apply -
        # this only lifts the implicit active=True filter for this widget.
        if spec.get("include_archived"):
            model = model.with_context(active_test=False)
        dimensions = spec.get("dimensions", [])
        measures = spec.get("measures", [])
        sort = spec.get("sort", "default")
        display_limit = spec.get("limit")
        group_others = spec.get("group_others", False)
        order = spec.get("order")
        # Hard bound on the grouped read so a high-cardinality dimension (or a
        # two-dim pivot cross-product) can never stream an unbounded result into
        # memory. Pivot lowers this; charts get the safety default.
        read_limit = spec.get("read_cap")
        # Exact top-N: when ranking by value with a display cap and NOT keeping an
        # "Others" bucket, push the aggregate ORDER + LIMIT into the grouped read
        # so the database returns the TRUE top groups. Without this, a dimension
        # with more distinct groups than the safety cap returns an arbitrary
        # capped slice that the Python sort then mis-ranks - silently the wrong
        # "top 10". (Group-others needs the full tail, so it keeps the safe read.)
        #
        # ONLY where the grouped read honours an aggregate ORDER term: Odoo 17+
        # _read_group does; Odoo 16's classic read_group silently drops it, so
        # pushing a small LIMIT there would return arbitrary (not top) groups.
        # On 16 we keep the safe read (safety-cap the read, then Python-sort +
        # cap), which is exact for any dimension under the safety cap.
        if (aggregation._ODOO_MAJOR >= 17
                and not order and display_limit and not group_others
                and sort in ("value_desc", "value_asc") and measures):
            pm = measures[0]
            # Only push the DB order when raw-aggregate order equals DISPLAY-value
            # order. A NEGATIVE multiplier flips the sign, so the DB's raw-top-N
            # are the display-BOTTOM-N; skip the push and let the Python sort (which
            # ranks the already-multiplied display values) pick the true top-N.
            if pm.get("verb") != "formula" and (pm.get("multiplier", 1.0) or 1.0) >= 0:
                if pm.get("verb") == "count" or not pm.get("field"):
                    token = "__count"
                else:
                    token = aggregation.measure_aggregate_token(
                        pm["field"], pm.get("verb", "sum"))
                order = "%s %s" % (token, "DESC" if sort == "value_desc" else "ASC")
                read_limit = display_limit

        def _run(_order, _limit):
            return aggregation.aggregate(
                model, spec.get("domain", []), dimensions, measures,
                order=_order, limit=_limit)

        try:
            result = _run(order, read_limit)
        except (ValueError, KeyError):
            # Any order term the grouped read rejects (the pushed top-N token OR a
            # caller-supplied field-sort that does not match the reduced group-by,
            # e.g. a decomposition's dimension-less total read): fall back to a
            # fully UNORDERED safe read so the widget still renders and, crucially,
            # the value/label sort in sort_and_cap still ranks it correctly.
            result = _run(None, spec.get("read_cap"))

        result = aggregation.sort_and_cap(
            result, sort, display_limit, group_others=group_others)
        # Advanced data shaping (opt-in per widget). Gap-fill only makes sense on
        # a single date series AND only for additive measures - zero-filling an
        # average/min/max gap would drag the series to a false 0.
        verbs = result.get("measure_verbs") or {}
        additive_keys = [k for k in result.get("measures", [])
                         if verbs.get(k, "sum") in ("sum", "count")]
        all_additive = len(additive_keys) == len(result.get("measures", []))
        if spec.get("fill_gaps") and len(dimensions) == 1 and all_additive:
            gran = dimensions[0].get("granularity")
            if gran:
                result["rows"] = aggregation.fill_time_gaps(result["rows"], gran)
        # A cumulative running total is meaningful only for additive measures;
        # never accumulate an avg/min/max/distinct series into a climbing sum.
        if spec.get("cumulative") and additive_keys:
            result["rows"] = aggregation.cumulate(result["rows"], additive_keys)
        return result

    def records(self, source, spec):
        """Read selected scalar columns without aggregation.

        Search/read runs on current-user recordset, so ACLs, record rules, and
        company scope remain enforced. Field count and row count are hard-bounded
        to keep a dashboard card from becoming an unbounded export endpoint.
        """
        model_name = spec.get("model") or source.model_name
        if not model_name or model_name not in source.env:
            return {"rows": [], "columns": [],
                    "error": "Unknown model %r" % model_name}
        model = source.env[model_name]
        ctx_company = spec.get("company_ids")
        if ctx_company:
            model = model.with_context(allowed_company_ids=ctx_company)
        if spec.get("include_archived"):
            model = model.with_context(active_test=False)

        allowed_types = {
            "boolean", "char", "text", "html", "selection", "many2one",
            "date", "datetime", "integer", "float", "monetary",
        }
        columns, names = [], []
        for col in (spec.get("fields") or [])[:12]:
            name = col.get("name")
            field = model._fields.get(name)
            if not name or not field or not field.store or field.type not in allowed_types:
                continue
            names.append(name)
            columns.append({
                "name": name,
                "label": col.get("label") or getattr(field, "string", None) or name,
                "type": field.type,
            })
        if not columns:
            return {"rows": [], "columns": [],
                    "error": "Choose at least one stored field to display."}

        requested = int(spec.get("limit") or 50)
        limit = max(1, min(requested, 500))
        order = spec.get("order") or "id desc"
        try:
            records = model.search(spec.get("domain") or [], order=order, limit=limit)
            values = records.read(names)
            definitions = model.fields_get(names, attributes=["selection"])
        except Exception:  # noqa: BLE001 - ACL/order failures become safe card errors
            _logger.exception("eh_board record-list read failed for %s", model_name)
            return {"rows": [], "columns": columns,
                    "error": "Could not read these records. Check model access, "
                             "selected fields, and sort settings."}

        selection_labels = {}
        for name in names:
            selection = (definitions.get(name) or {}).get("selection") or []
            selection_labels[name] = dict(selection)

        rows = []
        by_id = {row["id"]: row for row in values}
        for record in records:
            raw = by_id.get(record.id, {})
            cells = []
            for col in columns:
                value = raw.get(col["name"])
                if col["type"] == "many2one":
                    text = value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else ""
                elif col["type"] == "selection":
                    text = selection_labels[col["name"]].get(value, value or "")
                elif col["type"] == "boolean":
                    text = "Yes" if value else "No"
                elif value in (False, None):
                    text = ""
                else:
                    text = value
                cells.append({"value": value, "text": text, "type": col["type"]})
            rows.append({
                "id": record.id,
                "label": record.display_name or str(record.id),
                "cells": cells,
            })
        warning = None
        if requested > 500:
            warning = "Record lists are capped at 500 rows; showing the first 500."
        return {"rows": rows, "columns": columns, "warning": warning}

    def validate(self, source):
        problems = []
        if not source.model_id:
            problems.append("Choose a model for this data source.")
        return problems

    def preview(self, source, limit=20):
        if not source.model_id:
            return []
        model = source.env[source.model_name]
        return model.search_read(
            (source.get_domain() if hasattr(source, "get_domain") else []),
            [], limit=limit,
        )
