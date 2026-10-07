# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""File data source - dashboards straight from a CSV or Excel upload.

The deliberate contrast with the incumbent: an uploaded file is parsed to
normalised rows cached in ONE attachment and aggregated in Python here. It is
NEVER turned into an ``ir.model`` + a physical Postgres table + a row per line,
so there is no schema pollution, no orphan models on delete, no manual per-column
typing, and re-upload just rebuilds this source's own column list.

The spec contract is unchanged: the item resolves its group-by and measures to
plain column-name strings (see ``eh.board.item._resolve_spec`` tabular branch),
exactly as the ORM provider resolves field names.
"""
from odoo import _

from ..lib.registry import BoardDataSource, register_datasource
from ..lib import aggregation, tabular


@register_datasource
class FileDataSource(BoardDataSource):
    key = "file"
    label = "File (CSV / Excel)"
    read_only = True
    external = False
    tabular = True

    def aggregate(self, source, spec):
        measure_keys = spec.get("measure_keys", [])
        # The raw blob is Builder/Admin-gated, so never gate rendering on reading
        # it; the parsed rows (sudo-cached) are what the widget needs.
        rows = source._tabular_rows_for_item(spec.get("item_id"))
        if not rows and not source.column_ids:
            return {"rows": [], "measures": measure_keys, "dimensions": [],
                    "error": "This file source has no parsed data yet. Upload and "
                             "parse a CSV or Excel file."}

        # Guard against a column that was renamed/removed on a re-upload: drop
        # any dimension/measure whose column is gone and explain, rather than
        # aggregating a phantom key.
        known = set(source.column_ids.mapped("name"))
        try:
            rows = tabular.filter_records(rows, spec.get("domain"), known)
        except tabular.TabularError:
            return {"rows": [], "measures": measure_keys, "dimensions": [],
                    "error": _("The table filter uses an unsupported operator, incompatible value or missing column. Correct the filter before viewing these figures.")}
        dimensions, missing = [], []
        for d in spec.get("dimensions", []):
            if d["field"] in known:
                dimensions.append(d)
            else:
                missing.append(d["field"])
        measures = []
        for m in spec.get("measures", []):
            fld = m.get("field")
            verb = m.get("verb", "count")
            if fld and fld not in known:
                missing.append(fld)
                continue
            # A value verb (sum/avg/min/max) whose column was dropped on a
            # re-upload resolves to no field (ondelete=set null). Flag it as a
            # column that needs re-picking rather than silently summing to zero.
            if verb != "count" and not fld:
                labels = spec.get("measure_labels") or {}
                missing.append(labels.get(m.get("key")) or "a measure column")
                continue
            measures.append(m)

        result = tabular.aggregate_records(rows, dimensions, measures)
        result["measure_labels"] = spec.get("measure_labels", {})
        result = aggregation.sort_and_cap(
            result, spec.get("sort", "default"), spec.get("limit"),
            group_others=spec.get("group_others", False))
        # Gap-fill / cumulate only over additive measures (see orm.py): zero or
        # running-summing an avg/min/max series would ship a false number.
        verbs = result.get("measure_verbs") or {}
        additive_keys = [k for k in result.get("measures", [])
                         if verbs.get(k, "count") in ("sum", "count")]
        all_additive = len(additive_keys) == len(result.get("measures", []))
        if spec.get("fill_gaps") and len(dimensions) == 1 and all_additive:
            gran = dimensions[0].get("granularity")
            if gran:
                result["rows"] = aggregation.fill_time_gaps(result["rows"], gran)
        if spec.get("cumulative") and additive_keys:
            result["rows"] = aggregation.cumulate(result["rows"], additive_keys)
        if missing:
            result["error"] = (
                "Column(s) no longer in the file: %s. Re-pick a column."
                % ", ".join(sorted(set(missing))))
        # A file over the row cap was silently truncated at parse time; every
        # total below is therefore partial. Surface it so the viewer is never
        # shown an understated number with no indication it is incomplete.
        if source.truncated:
            result["warning"] = (
                "This file exceeds the %s-row limit, so it was truncated to the "
                "first %s rows. Totals and counts are partial." % (
                    tabular.MAX_ROWS, source.row_count or tabular.MAX_ROWS))
        return result

    def records(self, source, spec):
        """Bounded selected rows for file-backed individual-record lists."""
        rows = source._tabular_rows_for_item(spec.get("item_id"))
        known = {column.name: column for column in source.column_ids}
        try:
            rows = tabular.filter_records(rows, spec.get("domain"), known)
        except tabular.TabularError:
            return {"rows": [], "columns": [],
                    "error": _("The table filter uses an unsupported operator, incompatible value or missing column. Correct the filter before viewing these figures.")}
        columns = []
        for requested in (spec.get("fields") or [])[:12]:
            name = requested.get("name")
            if name in known:
                columns.append({
                    "name": name,
                    "label": requested.get("label") or known[name].label or name,
                    "type": requested.get("type") or "char",
                })
        if not columns:
            return {"rows": [], "columns": [],
                    "error": "Choose at least one file column to display."}
        requested_limit = int(spec.get("limit") or 50)
        limit = max(1, min(requested_limit, 500))
        output = []
        for index, raw in enumerate(rows[:limit], start=1):
            cells = []
            for column in columns:
                value = raw.get(column["name"])
                if column["type"] == "boolean":
                    text = _("Yes") if value else _("No")
                elif value is None or value is False:
                    text = ""
                else:
                    text = value
                cells.append({
                    "value": value, "text": text, "type": column["type"],
                })
            output.append({
                "id": index,
                "label": str((raw.get(columns[0]["name"]) if columns else "") or index),
                "cells": cells,
            })
        warnings = []
        if requested_limit > 500:
            warnings.append("File record lists are capped at 500 rows.")
        if source.truncated:
            warnings.append(
                "Source file was truncated to %s rows; displayed data is partial."
                % (source.row_count or tabular.MAX_ROWS))
        return {
            "rows": output, "columns": columns,
            "warning": " ".join(warnings) or None,
        }

    def validate(self, source):
        problems = []
        if not source.file_data:
            problems.append("Upload a CSV or Excel file.")
        elif not source.column_ids:
            problems.append("Click Parse to read the file's columns.")
        return problems

    def preview(self, source, limit=20):
        return source.tabular_rows()[:limit]
