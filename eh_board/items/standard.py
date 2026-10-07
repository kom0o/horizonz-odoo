# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The standard item-type catalogue.

Each type is a small class registered with ``@register_item_type``. The shared
``StandardItem`` does all the aggregation and shaping, so a new Cartesian chart
is just a class with a ``key``, a ``label`` and an icon - the promise of the
registry moat, demonstrated. KPI / tile types shape a single value with an
optional comparison; content types (rich text, to-do) carry no data.
"""

from datetime import timedelta

from dateutil.relativedelta import relativedelta
from odoo import fields

from ..lib.registry import (
    BoardItemType, register_item_type, get_datasource,
)
from ..lib import aggregation
from ..lib.formula import compile_formula, FormulaError

# Calculated measures address the item's base measures as a, b, c ... in order.
_FORMULA_VARS = ("a", "b", "c", "d", "e", "f")


def apply_formulas(spec, result):
    """Compute each calculated measure per row from the base measures, then add
    it to the result so it renders as just another series."""
    formulas = spec.get("formula_measures") or []
    if not formulas:
        return result
    base = spec.get("base_measure_keys", [])
    compiled = []
    for f in formulas:
        try:
            compiled.append((f["key"], compile_formula(f["formula"])))
        except FormulaError:
            compiled.append((f["key"], None))
    for row in result.get("rows", []):
        vals = row["values"]
        variables = {var: vals.get(base[i], 0.0)
                     for i, var in enumerate(_FORMULA_VARS) if i < len(base)}
        for key, fn in compiled:
            vals[key] = fn(variables) if fn else 0.0
    # Render series in the item's own measure order (so a formula can be first).
    result["measures"] = spec.get("all_measure_keys") \
        or (list(result.get("measures", [])) + [f["key"] for f in formulas])
    result["measure_labels"] = spec.get("measure_labels") or result.get("measure_labels")
    return result


class StandardItem(BoardItemType):
    """Grouped chart / list: aggregate through the datasource, shape to series."""

    def build(self, item, options):
        spec = item._resolve_spec(options)
        source = item.datasource_id
        provider = get_datasource(source.provider_type) if source else None
        if not provider:
            return {"type": self.key, "component": self.component(),
                    "rows": [], "error": "No data source configured."}
        result = provider.aggregate(source, spec)
        result = apply_formulas(spec, result)
        grand_total = self._grand_total(provider, source, spec) \
            if spec.get("measure_calculations") else {}
        comparison = self._comparison(item, options, provider, source) \
            if self.category == "chart" else None
        return self.shape(item, result, spec, options, grand_total, comparison)

    def _comparison(self, item, options, provider, source):
        """Fetch same chart over prior equal window; never fake all-time compare."""
        measure = item.measure_ids[:1]
        date_range = (options or {}).get("date_range") or {}
        if (not measure or measure.compare_mode == "none"
                or source.provider_type != "orm" or not item._global_date_field()
                or not date_range.get("start") or not date_range.get("end")):
            return None
        try:
            start = fields.Date.to_date(date_range["start"])
            end = fields.Date.to_date(date_range["end"])
        except (TypeError, ValueError):
            return None
        if not start or not end or start > end:
            return None
        if measure.compare_mode == "prev_year":
            previous_start = start - relativedelta(years=1)
            previous_end = end - relativedelta(years=1)
            label = "Same period last year"
        else:
            span = (end - start).days + 1
            previous_end = start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=span - 1)
            label = "Previous period"
        previous_options = dict(options or {})
        previous_options["date_range"] = {
            "start": previous_start.isoformat(), "end": previous_end.isoformat(),
        }
        previous_spec = item._resolve_spec(previous_options)
        try:
            previous = apply_formulas(
                previous_spec, provider.aggregate(source, previous_spec))
        except Exception:  # noqa: BLE001 - current chart remains useful alone
            return None
        return {
            "label": label,
            "mode": measure.compare_mode,
            "rows": previous.get("rows") or [],
            "measures": previous.get("measures") or [],
            "domain": item._date_window_domain(
                item._global_date_field(), previous_start, previous_end),
        }

    def _grand_total(self, provider, source, spec):
        """Exact no-dimension denominator for grouped-list percentages.

        Summing displayed rows is wrong for averages/min/max/distinct counts and
        wrong whenever a top-N limit hides groups.  One dedicated grouped read
        computes each aggregate at grand-total grain, then formulas run over
        those aggregate totals exactly like pivot margins.
        """
        total_spec = dict(spec)
        total_spec.update({
            "dimensions": [], "limit": None, "read_cap": None,
            "sort": "default", "order": None, "group_others": False,
            "cumulative": False, "fill_gaps": False,
        })
        try:
            total_result = apply_formulas(
                total_spec, provider.aggregate(source, total_spec))
        except Exception:  # noqa: BLE001 - table still renders without companion
            return {}
        rows = total_result.get("rows") or []
        return dict(rows[0].get("values") or {}) if rows else {}

    def shape(self, item, result, spec, options, grand_total=None, comparison=None):
        rows = result.get("rows", [])
        dims = spec.get("dimensions", [])
        measure_keys = result.get("measures", [])
        # Gap-fill a single date series for charts, but only when every measure is
        # additive: zero-filling an average/min/max gap would drag the line to a
        # false 0. (The provider may have gap-filled already; this is idempotent.)
        _verbs = result.get("measure_verbs") or {}
        _all_additive = all(_verbs.get(k, "sum") in ("sum", "count") for k in measure_keys)
        if (self.category == "chart" and len(dims) == 1
                and dims[0].get("granularity") and _all_additive):
            rows = aggregation.fill_time_gaps(rows, dims[0]["granularity"])
        # Provider-supplied labels (e.g. a join's "Ordered"/"Invoiced") win over
        # the item's own; falls back to the item measure labels then the key.
        labels = result.get("measure_labels") or spec.get("measure_labels", {})
        # A flat series per measure for single-dimension charts; the OWL side
        # pivots multi-dimension rows into grouped/stacked series itself.
        line_keys = set(spec.get("line_measures") or [])
        series = []
        for mk in measure_keys:
            series.append({
                "key": mk,
                "label": labels.get(mk, mk),
                "data": [r["values"].get(mk, 0.0) for r in rows],
                "as_line": mk in line_keys,   # combo: draw this series as a line
                "number_format": (spec.get("measure_formats") or {}).get(
                    mk, spec.get("number_format", "compact")),
                "unit": (spec.get("measure_units") or {}).get(mk, ""),
                "currency": (spec.get("measure_currencies") or {}).get(mk),
            })
        comparison_range = []
        if comparison and comparison.get("rows"):
            previous_rows = comparison["rows"]
            if (len(dims) == 1 and dims[0].get("granularity") and _all_additive):
                previous_rows = aggregation.fill_time_gaps(
                    previous_rows, dims[0]["granularity"])
            dated_axis = bool(item.primary_dimension_id.sudo()
                              and item.primary_dimension_id.sudo().ttype in ("date", "datetime"))
            by_key = {
                repr((row.get("keys") or [None])[0]): row
                for row in previous_rows
            }
            for index, mk in enumerate(measure_keys):
                source_series = series[index] if index < len(series) else {}
                if dated_axis:
                    data = [
                        (previous_rows[position].get("values") or {}).get(mk, 0.0)
                        if position < len(previous_rows) else 0.0
                        for position in range(len(rows))
                    ]
                else:
                    data = [
                        (by_key.get(repr((row.get("keys") or [None])[0]), {})
                         .get("values") or {}).get(mk, 0.0)
                        for row in rows
                    ]
                series.append({
                    **source_series,
                    "key": "%s__comparison" % mk,
                    "label": "%s · %s" % (
                        source_series.get("label", labels.get(mk, mk)),
                        comparison["label"]),
                    "data": data,
                    "as_line": False,
                    "comparison": True,
                    "comparison_domain": comparison.get("domain") or [],
                })
            comparison_range = comparison.get("domain") or []
        target_series = None
        first_measure = item.measure_ids[:1]
        target_values = first_measure.dated_targets_for_rows(rows) \
            if first_measure else []
        if target_values:
            target_series = {
                "label": "Target",
                "data": target_values,
                "number_format": spec.get("number_format", "compact"),
                "unit": spec.get("unit", ""),
                "currency": spec.get("currency"),
            }
        return {
            "type": self.key,
            "component": self.component(),
            "category": self.category,
            "labels": [(r["labels"][0] if r["labels"] else "") for r in rows],
            "rows": rows,
            "series": series,
            "measure_keys": measure_keys,
            "measure_labels": labels,
            "measure_calculations": spec.get("measure_calculations") or {},
            "measure_aggregates": spec.get("measure_aggregates") or {},
            "grand_total": grand_total or {},
            "secondary": len(dims) > 1,
            "number_format": spec.get("number_format", "compact"),
            "unit": spec.get("unit", ""),
            "currency": spec.get("currency"),
            "target_series": target_series,
            "comparison_range": comparison_range,
            "error": result.get("error"),
            "warning": result.get("warning"),
        }


class KpiItem(BoardItemType):
    """Single headline number with an optional target and period comparison."""

    category = "kpi"
    needs_dimension = False
    allow_secondary = False
    # Header chrome plus icon/value/label cannot remain legible below four
    # rows. The old 3x3 default shrank the 40px headline to a 4px sliver.
    default_size = (3, 4)
    min_size = (2, 4)

    def build(self, item, options):
        spec = item._resolve_spec(options, no_dimension=True)
        source = item.datasource_id
        provider = get_datasource(source.provider_type) if source else None
        if not provider:
            return {"type": self.key, "component": self.component(),
                    "value": 0.0, "error": "No data source configured."}
        result = provider.aggregate(source, spec)
        result = apply_formulas(spec, result)
        rows = result.get("rows", [])
        measure_keys = result.get("measures", [])
        primary = measure_keys[0] if measure_keys else None
        # SQL/join sources already return shaped rows and do not have an item
        # measure record. A headline widget over grouped output means its first
        # numeric result column TOTAL, never an arbitrary first category.
        if source.provider_type in ("join", "sql") and primary:
            value = sum((row.get("values") or {}).get(primary, 0.0) or 0.0
                        for row in rows)
        else:
            value = rows[0]["values"].get(primary, 0.0) if (rows and primary) else 0.0
        payload = {
            "type": self.key,
            "component": self.component(),
            "category": self.category,
            "value": value,
            "measure_key": primary,
            "number_format": spec.get("number_format", "compact"),
            "unit": spec.get("unit", ""),
            "currency": spec.get("currency"),
            "history": item._snapshot_history(),
            "error": result.get("error"),
            "warning": result.get("warning"),
        }
        payload.update(item._resolve_comparison(options, value))
        return payload

    def validate(self, item):
        return super().validate(item)


class ContentItem(BoardItemType):
    """No-data item (rich text / heading, or a to-do checklist)."""

    category = "content"
    needs_measure = False
    needs_dimension = False
    allow_secondary = False

    def build(self, item, options):
        from odoo.tools import html_sanitize
        return {
            "type": self.key,
            "component": self.component(),
            "category": self.category,
            # Sanitised on render (strips <script>/on*= /javascript:) so even a
            # Builder cannot land stored XSS in a shared board's text block.
            "content": html_sanitize(item.content or ""),
        }

    def validate(self, item):
        return []


@register_item_type
class DecompType(BoardItemType):
    """Decomposition tree: a measure total broken down level by level along the
    dimension chain (primary dimension + drill steps). Click a node to expand
    it by the next dimension - Power BI's decomposition tree, offline."""

    key = "decomp"
    label = "Decomposition"
    icon = "fa-sitemap"
    category = "chart"
    needs_measure = True
    needs_dimension = True
    allow_secondary = False
    js_component = "decomp"
    default_size = (6, 7)
    min_size = (4, 5)

    def build(self, item, options):
        chain = item._decomp_fields()
        first = item.get_decomp([], options) if chain else {"nodes": [], "total": 0}
        measure = item.measure_ids[:1]
        return {
            "type": "decomp",
            "component": self.component(),
            "category": self.category,
            "chain": chain,
            "chain_labels": item._decomp_labels(),
            "root": {"label": (measure.name if measure else "Total"),
                     "value": first.get("total", 0)},
            "level0": first,
            "number_format": (measure.number_format if measure else "compact") or "compact",
            "unit": (measure.unit if measure else "") or "",
            "currency": ({
                "id": measure.currency_id.id,
                "code": measure.currency_id.name,
                "symbol": measure.currency_id.symbol or measure.currency_id.name,
                "position": measure.currency_id.position or "before",
                "decimal_places": measure.currency_id.decimal_places,
            } if measure and measure.currency_id else None),
        }

    def validate(self, item):
        if not item._decomp_fields():
            return ["Add a Group by (and optional drill steps) to decompose the measure."]
        return []


@register_item_type
class SlicerType(BoardItemType):
    """On-canvas slicer: a field's values as clickable chips that cross-filter
    every widget on the board (Power BI-style sync slicer). No measure."""

    key = "slicer"
    label = "Slicer"
    icon = "fa-filter"
    category = "control"
    needs_measure = False
    needs_dimension = True
    allow_secondary = False
    js_component = "slicer"
    default_size = (3, 5)
    min_size = (2, 3)

    def build(self, item, options):
        field = item.primary_dimension_id.sudo()
        return {
            "type": self.key,
            "component": self.component(),
            "category": self.category,
            "field": field.name if field else None,
            "values": self._field_values(item, field) if (field and item.datasource_id) else [],
        }

    def _field_values(self, item, field, limit=80):
        env = item.env
        if field.ttype == "many2one" and field.relation and field.relation in env:
            recs = env[field.relation].search([], limit=limit)
            return [{"key": r.id, "label": r.display_name} for r in recs]
        model = item.datasource_id.model_name
        if not model or model not in env:
            return []
        Model = env[model]
        if field.ttype == "selection":
            try:
                sels = Model.fields_get([field.name])[field.name].get("selection", [])
            except Exception:  # noqa: BLE001
                sels = []
            return [{"key": v, "label": lbl} for v, lbl in sels]
        out = []
        # Bound the grouped read itself (not just a Python slice), so a slicer on
        # a high-cardinality field never full-table GROUP BYs a large model.
        for row in aggregation.grouped_read(Model, [], [field.name], [], limit=limit):
            v = row[0]
            if v is None or v is False:
                continue
            out.append({"key": getattr(v, "id", v),
                        "label": getattr(v, "display_name", str(v))})
        return out

    def validate(self, item):
        if not item.primary_dimension_id.sudo():
            return ["Pick a field for the slicer."]
        return []


# ---------------------------------------------------------------------------
# KPI / tile
# ---------------------------------------------------------------------------

@register_item_type
class TileType(KpiItem):
    key = "tile"
    label = "Tile"
    icon = "fa-square"
    js_component = "tile"


@register_item_type
class KpiType(KpiItem):
    key = "kpi"
    label = "KPI"
    icon = "fa-tachometer"
    js_component = "kpi"


# ---------------------------------------------------------------------------
# Cartesian + radial charts
# ---------------------------------------------------------------------------

@register_item_type
class BarType(StandardItem):
    key = "bar"
    label = "Bar"
    icon = "fa-bar-chart"


@register_item_type
class HBarType(StandardItem):
    key = "hbar"
    label = "Horizontal Bar"
    icon = "fa-align-left"
    js_component = "bar"


@register_item_type
class ColumnType(StandardItem):
    key = "column"
    label = "Stacked Column"
    icon = "fa-bars"
    js_component = "bar"


@register_item_type
class LineType(StandardItem):
    key = "line"
    label = "Line"
    icon = "fa-line-chart"


@register_item_type
class AreaType(StandardItem):
    key = "area"
    label = "Area"
    icon = "fa-area-chart"
    js_component = "line"


@register_item_type
class PieType(StandardItem):
    key = "pie"
    label = "Pie"
    icon = "fa-pie-chart"
    allow_secondary = False


@register_item_type
class DoughnutType(StandardItem):
    key = "doughnut"
    label = "Doughnut"
    icon = "fa-circle-o"
    js_component = "pie"
    allow_secondary = False


@register_item_type
class RadarType(StandardItem):
    key = "radar"
    label = "Radar"
    icon = "fa-star-o"
    allow_secondary = True


@register_item_type
class FunnelType(StandardItem):
    key = "funnel"
    label = "Funnel"
    icon = "fa-filter"
    allow_secondary = False


@register_item_type
class PyramidType(StandardItem):
    key = "pyramid"
    label = "Pyramid"
    icon = "fa-sort-amount-asc"
    js_component = "funnel"
    allow_secondary = False


@register_item_type
class ScatterType(StandardItem):
    key = "scatter"
    label = "Scatter"
    icon = "fa-braille"
    allow_secondary = False


@register_item_type
class PolarType(StandardItem):
    """Polar-area chart: a pie whose slices vary in radius by value."""
    key = "polar"
    label = "Polar Area"
    icon = "fa-life-ring"
    allow_secondary = False


@register_item_type
class RadialType(StandardItem):
    """Radial bar: one concentric progress ring per category."""
    key = "radial"
    label = "Radial Bar"
    icon = "fa-circle-o-notch"
    allow_secondary = False


@register_item_type
class RoseType(StandardItem):
    """Rose (Nightingale / coxcomb): equal-angle petals, radius linear in value."""
    key = "rose"
    label = "Rose"
    icon = "fa-pagelines"
    allow_secondary = False


@register_item_type
class MapType(StandardItem):
    """World choropleth: countries filled by a measure value.

    Beats the incumbent's pin map: when the group-by is a country field, each
    country outline is coloured by the number (an original SVG choropleth, no
    amCharts). For any other dimension it degrades client-side to a ranked
    coloured bar list, so it is always a useful visual."""
    key = "map"
    label = "Map (Choropleth)"
    icon = "fa-globe"
    category = "chart"
    allow_secondary = False
    default_size = (6, 6)

    def shape(self, item, result, spec, options, grand_total=None, comparison=None):
        payload = super().shape(
            item, result, spec, options, grand_total, comparison)
        payload["degrade"] = True
        if payload.get("error"):
            return payload
        dim = item.primary_dimension_id.sudo()
        is_country = bool(
            dim and dim.ttype == "many2one" and dim.relation == "res.country")
        if not is_country:
            return payload
        rows = result.get("rows", [])
        mkeys = result.get("measures", [])
        mk = mkeys[0] if mkeys else None
        ids = [r["keys"][0] for r in rows
               if r.get("keys") and isinstance(r["keys"][0], int)]
        code_by_id = {
            c.id: (c.code, c.name)
            for c in item.env["res.country"].browse(ids)}
        regions = []
        for i, r in enumerate(rows):
            key = (r.get("keys") or [None])[0]
            code, name = code_by_id.get(key, (None, None))
            if code:
                label = (r.get("labels") or [None])[0]
                regions.append({
                    "code": code.upper(),
                    "name": name or label or code,
                    "value": r["values"].get(mk, 0.0) if mk else 0.0,
                    # Row index so a click drills / cross-filters through the same
                    # row-based path as every other chart (the ISO code alone
                    # cannot scope the country many2one).
                    "index": i,
                })
        if regions:
            payload["regions"] = regions
            payload["degrade"] = False
        return payload


@register_item_type
class HeatmapType(StandardItem):
    """Heat map: a coloured grid of a measure across two dimensions."""
    key = "heatmap"
    label = "Heat Map"
    icon = "fa-th"
    allow_secondary = True
    default_size = (6, 6)


@register_item_type
class BulletType(KpiItem):
    """Bullet: a dense actual-vs-target bar with qualitative bands."""
    key = "bullet"
    label = "Bullet"
    category = "chart"
    icon = "fa-tachometer"
    needs_dimension = False
    allow_secondary = False
    default_size = (4, 3)


@register_item_type
class GaugeType(KpiItem):
    """Gauge / meter with a target - a single value against a goal, nearly
    absent in the market. Behaves like a KPI (value + target), rendered as an
    arc rather than a number."""
    key = "gauge"
    label = "Gauge"
    category = "chart"
    icon = "fa-dashboard"
    needs_dimension = False
    allow_secondary = False
    default_size = (3, 4)


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

@register_item_type
class ListType(StandardItem):
    key = "list"
    label = "List"
    category = "table"
    icon = "fa-table"
    default_size = (6, 6)

    def build(self, item, options):
        if item.list_mode == "records":
            source = item.datasource_id
            provider = get_datasource(source.provider_type) if source else None
            if not provider:
                return {"type": self.key, "component": self.component(),
                        "category": self.category, "record_list": True,
                        "rows": [], "columns": [],
                        "error": "No data source configured."}
            result = provider.records(source, item._resolve_record_list_spec(options))
            return {
                "type": self.key,
                "component": self.component(),
                "category": self.category,
                "record_list": True,
                "rows": result.get("rows", []),
                "columns": result.get("columns", []),
                "measure_keys": [],
                "series": [],
                "error": result.get("error"),
                "warning": result.get("warning"),
            }

        payload = super().build(item, options)
        calculations = payload.get("measure_calculations") or {}
        if not calculations or payload.get("error"):
            return payload
        spec = item._resolve_spec(options)
        total_spec = dict(spec)
        total_spec.update({
            "dimensions": [], "limit": None, "read_cap": None,
            "order": None, "sort": "default", "group_others": False,
            "cumulative": False, "fill_gaps": False,
        })
        source = item.datasource_id
        provider = get_datasource(source.provider_type) if source else None
        try:
            total_result = provider.aggregate(source, total_spec)
            total_result = apply_formulas(spec, total_result)
            keys = total_result.get("measures", [])
            payload["grand_total"] = {
                key: sum((row.get("values") or {}).get(key, 0) or 0
                         for row in total_result.get("rows", []))
                for key in keys
            }
        except Exception:  # noqa: BLE001 - values still render without companion %
            payload["grand_total"] = {}
        return payload

    def validate(self, item):
        if item.list_mode != "records":
            return super().validate(item)
        problems = []
        source = item.datasource_id
        provider = get_datasource(source.provider_type) if source else None
        if not source:
            problems.append("Choose a data source.")
        elif provider:
            problems.extend(provider.validate(source))
            if provider.key not in ("orm", "file"):
                problems.append(
                    "Individual-record lists require an Odoo model or file source.")
        if not item.list_field_ids and not (
                source and source.provider_type == "file" and item.list_field_order):
            problems.append("Choose at least one field to display.")
        return problems


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

@register_item_type
class RichTextType(ContentItem):
    key = "richtext"
    label = "Text / Heading"
    icon = "fa-font"
    js_component = "richtext"


@register_item_type
class TodoType(ContentItem):
    key = "todo"
    label = "To-Do"
    icon = "fa-check-square-o"
    js_component = "todo"
