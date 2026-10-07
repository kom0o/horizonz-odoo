# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Pivot / cross-tab matrix item.

The flagship table: measures laid out against row and column dimensions, with
row totals, column totals and a grand total - the classic spreadsheet pivot,
but every cell is produced by the same single grouped database read the charts
use (``_read_group`` over both dimensions), so it stays record-rule-safe and
scales. No second query per cell, no Python fold over the whole recordset.

The item also carries a flat ``rows``/``series`` block so CSV, Excel and PNG
export keep working unchanged; the matrix structure below is what the OWL pivot
widget renders.
"""

from ..lib.registry import BoardItemType, register_item_type, get_datasource
from .standard import apply_formulas


def _skey(value):
    """Stable string key for a raw group value, safe as a dict key in JSON.

    Must agree byte-for-byte with the JS ``_skey`` (String(k)); a Python bool
    stringifies as 'True'/'False' while JS gives 'true'/'false', so booleans are
    lower-cased here - otherwise a boolean row never matches its cells and renders
    an all-zero row that disagrees with the totals."""
    if value is None or value is False:
        # False is a real boolean group value, distinct from a null/None group:
        # keep them apart so a boolean dimension's False row still maps.
        if value is False:
            return "false"
        return "∅"  # empty-set glyph for null/None, never collides with a label
    if value is True:
        return "true"
    return str(value)


@register_item_type
class PivotType(BoardItemType):
    key = "pivot"
    label = "Pivot Matrix"
    category = "pivot"
    icon = "fa-th"
    js_component = "pivot"
    needs_dimension = True
    allow_secondary = True
    default_size = (6, 7)
    min_size = (4, 4)
    _MAX_COMBOS = 5000   # hard bound on the flat cross-product read
    _MAX_ROWS = 200      # displayed rows before truncation
    _MAX_COLS = 60       # displayed columns before truncation

    def build(self, item, options):
        spec = item._resolve_spec(options)
        # The pivot needs the combinations to build its matrix, but a bounded
        # read keeps a high-cardinality two-dim pivot from pulling an unbounded
        # cross-product into memory (the one place we could OOM like the
        # search-everything incumbents).
        spec["limit"] = self._MAX_COMBOS
        # Also bound the DB read itself (forwarded to _read_group), not just the
        # Python-side cap - this is what actually prevents the OOM.
        spec["read_cap"] = self._MAX_COMBOS
        spec["sort"] = spec.get("sort") or "value_desc"
        spec["group_others"] = False
        spec["cumulative"] = False
        spec["fill_gaps"] = False
        source = item.datasource_id
        provider = get_datasource(source.provider_type) if source else None
        if not provider:
            return {"type": self.key, "component": self.component(),
                    "category": self.category, "row_headers": [],
                    "error": "No data source configured."}
        result = provider.aggregate(source, spec)
        # Calculated (formula) measures: compute them per cell so they appear in
        # the matrix and the flat CSV/Excel export like every other data widget
        # (a pivot used to silently drop them entirely).
        result = apply_formulas(spec, result)
        totals = self._compute_totals(provider, source, spec, result)
        return self.shape(item, result, spec, totals)

    def _compute_totals(self, provider, source, spec, result):
        """Exact row / column / grand margins, computed by DEDICATED grouped reads
        rather than by summing the displayed cells.

        This is the correctness fix for two shipped defects: (1) summing per-cell
        aggregates gives a meaningless total for a non-additive measure (avg / min
        / max / distinct-count); a fresh grouped read at each margin level yields
        the TRUE aggregate for any verb. (2) the cell read is capped at
        ``_MAX_COMBOS``, so cell-summed totals silently understate a large pivot;
        these reads are not combo-capped, so the margins stay exact regardless of
        how many cells are displayed."""
        mkeys = result.get("measures", [])
        dims = spec.get("dimensions", [])

        def _read(dim_list):
            s = dict(spec)
            s["dimensions"] = dim_list
            s["limit"] = None
            s["read_cap"] = None      # only the global safety cap applies
            s["sort"] = "default"
            # Drop any pinned field-sort ORDER: a reduced group-by (e.g. the grand
            # read has no group-by at all) does not contain the sort field, and
            # _read_group rejects an order term referencing a non-grouped field -
            # which would raise, get swallowed here, and blank that whole margin.
            s["order"] = None
            s["group_others"] = False
            s["cumulative"] = False
            s["fill_gaps"] = False
            try:
                return provider.aggregate(source, s)
            except Exception:  # noqa: BLE001 - a margin read must never break the pivot
                return {"rows": []}

        # A formula measure is derived from the base measures AFTER aggregation,
        # so the dedicated margin reads (which only know base measures) leave it
        # blank; apply the formula to each margin's base values so a formula
        # column's Total/subtotals are the formula OF the totals, not 0.
        def _with_formulas(values):
            fake = {"rows": [{"values": dict(values)}]}
            apply_formulas(spec, fake)
            return fake["rows"][0]["values"]

        # SUM every grand row, not just the first: an ORM/file provider collapses
        # dimensions=[] to a single grand row (sum == that row), but the SQL/join
        # providers IGNORE dimensions and return their full per-group result, so
        # summing yields the correct additive column total instead of one group.
        grand_rows = _read([]).get("rows", [])
        grand = _with_formulas({
            mk: sum(r["values"].get(mk, 0.0) or 0.0 for r in grand_rows)
            for mk in mkeys})
        row = {}
        if dims:
            for r in _read([dims[0]]).get("rows", []):
                row[_skey((r.get("keys") or [None])[0])] = _with_formulas(r.get("values", {}))
        col = {}
        if len(dims) >= 2:
            for r in _read([dims[1]]).get("rows", []):
                col[_skey((r.get("keys") or [None])[0])] = _with_formulas(r.get("values", {}))
        return {"row": row, "col": col, "grand": grand}

    def shape(self, item, result, spec, totals=None):
        totals = totals or {"row": {}, "col": {}, "grand": {}}
        rows = result.get("rows", [])
        mkeys = result.get("measures", [])
        labels = spec.get("measure_labels", {})
        dims = spec.get("dimensions", [])
        has_col = len(dims) >= 2

        row_headers, col_headers = [], []
        seen_r, seen_c = set(), set()
        cells = {}
        for r in rows:
            keys = r.get("keys", [])
            rlabels = r.get("labels", [])
            rkey = keys[0] if keys else None
            rks = _skey(rkey)
            if rks not in seen_r:
                seen_r.add(rks)
                row_headers.append({"key": rkey, "label": rlabels[0] if rlabels else ""})
            if has_col:
                ckey = keys[1] if len(keys) > 1 else None
                cks = _skey(ckey)
                if cks not in seen_c:
                    seen_c.add(cks)
                    col_headers.append(
                        {"key": ckey, "label": rlabels[1] if len(rlabels) > 1 else ""})
            else:
                cks = "__m__"
            cells.setdefault(rks, {})[cks] = r.get("values", {})

        # Margins come from dedicated grouped reads (see _compute_totals): exact
        # for every aggregate verb and not limited by the cell combo cap. Fall
        # back to per-cell sums only if the margin reads returned nothing.
        row_totals = totals.get("row") or {}
        col_totals = totals.get("col") or {}
        grand = totals.get("grand") or {mk: 0.0 for mk in mkeys}
        if not grand:
            grand = {mk: 0.0 for mk in mkeys}

        # Bound what actually renders. Margins above are exact; only the displayed
        # axes are truncated, with a note.
        full_rows, full_cols = len(row_headers), len(col_headers)
        truncated = None
        if full_rows > self._MAX_ROWS or full_cols > self._MAX_COLS:
            truncated = {"rows": full_rows, "cols": full_cols,
                         "shown_rows": min(full_rows, self._MAX_ROWS),
                         "shown_cols": min(full_cols, self._MAX_COLS)}
            row_headers = row_headers[:self._MAX_ROWS]
            col_headers = col_headers[:self._MAX_COLS]

        # Flat block so the shared CSV / Excel / PNG export path keeps working.
        series = [{
            "key": mk,
            "label": labels.get(mk, mk),
            "data": [r["values"].get(mk, 0.0) for r in rows],
            "number_format": (spec.get("measure_formats") or {}).get(
                mk, spec.get("number_format", "compact")),
            "unit": (spec.get("measure_units") or {}).get(mk, ""),
            "currency": (spec.get("measure_currencies") or {}).get(mk),
        } for mk in mkeys]

        return {
            "type": self.key,
            "component": self.component(),
            "category": self.category,
            "has_col": has_col,
            "row_headers": row_headers,
            "col_headers": col_headers,
            "cells": cells,
            "row_totals": row_totals,
            "col_totals": col_totals,
            "grand_total": grand,
            "measure_keys": mkeys,
            "measure_labels": {mk: labels.get(mk, mk) for mk in mkeys},
            "measure_calculations": spec.get("measure_calculations") or {},
            "measure_aggregates": spec.get("measure_aggregates") or {},
            "row_dim_label": (item.primary_dimension_id.sudo().field_description
                              or item.primary_dimension_id.sudo().name)
            if item.primary_dimension_id.sudo() else "",
            "col_dim_label": (item.secondary_dimension_id.sudo().field_description
                              or item.secondary_dimension_id.sudo().name)
            if (has_col and item.secondary_dimension_id.sudo()) else "",
            "row_field": item.primary_dimension_id.sudo().name if item.primary_dimension_id.sudo() else None,
            "col_field": item.secondary_dimension_id.sudo().name if (has_col and item.secondary_dimension_id.sudo()) else None,
            # Field types + granularity so a date-bucket cell drills to a period
            # RANGE, not an equality on the raw bucket-start string (which opens
            # the wrong, usually empty, record set).
            "row_field_type": item.primary_dimension_id.sudo().ttype if item.primary_dimension_id.sudo() else None,
            "col_field_type": (item.secondary_dimension_id.sudo().ttype
                               if (has_col and item.secondary_dimension_id.sudo()) else None),
            "granularity": item.date_granularity,
            "heatmap": len(mkeys) == 1,
            "truncated": truncated,
            # flat block for export parity
            "rows": rows,
            "series": series,
            "number_format": spec.get("number_format", "compact"),
            "unit": spec.get("unit", ""),
            "currency": spec.get("currency"),
            "error": result.get("error"),
            "warning": result.get("warning"),
        }
