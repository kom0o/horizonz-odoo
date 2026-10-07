# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
import ast
from datetime import datetime, time, timedelta
import math
import re

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_sanitize

from ..lib.registry import item_type_selection, get_item_type, get_datasource


class EhBoardItem(models.Model):
    _name = "eh.board.item"
    _description = "Dashboard Item"
    _order = "sequence, id"

    dashboard_id = fields.Many2one(
        "eh.board.dashboard", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    title = fields.Char()
    subtitle = fields.Char()
    item_type = fields.Selection(
        selection=lambda self: item_type_selection(),
        required=True, default="bar",
        help="The kind of widget. Every type is a registered strategy - adding "
             "one never edits this model.",
    )
    datasource_id = fields.Many2one(
        "eh.board.datasource", string="Data Source", ondelete="restrict")
    model_id = fields.Many2one(related="datasource_id.model_id", readonly=True)
    model_name = fields.Char(
        related="datasource_id.model_name", readonly=True, string="Model Technical Name")
    provider_type = fields.Selection(
        related="datasource_id.provider_type", readonly=True,
        string="Provider")
    measure_ids = fields.Many2many(
        "eh.board.measure", string="Measures",
        domain="[('datasource_id', '=', datasource_id)]")
    # set null (not cascade): deleting the grouped field should clear the
    # group-by and let the widget degrade, never delete the whole widget - the
    # same behaviour as the other four ir.model.fields references below.
    primary_dimension_id = fields.Many2one(
        "ir.model.fields", string="Group by",
        domain="[('model_id', '=', model_id)]", ondelete="set null")
    secondary_dimension_id = fields.Many2one(
        "ir.model.fields", string="Then by",
        domain="[('model_id', '=', model_id)]", ondelete="set null")
    # Tabular (file / REST) sources group by a parsed column, not an
    # ir.model.fields - the anti-pollution mirror of the dimension pickers.
    primary_column_id = fields.Many2one(
        "eh.board.source.column", string="Group by column",
        domain="[('datasource_id', '=', datasource_id)]", ondelete="set null")
    secondary_column_id = fields.Many2one(
        "eh.board.source.column", string="Then by column",
        domain="[('datasource_id', '=', datasource_id)]", ondelete="set null")
    list_mode = fields.Selection(
        [("grouped", "Grouped summary"), ("records", "Individual records")],
        default="grouped", required=True,
        help="Grouped summary aggregates records by dimensions. Individual "
             "records displays selected model fields as table columns.")
    list_field_ids = fields.Many2many(
        "ir.model.fields", "eh_board_item_list_field_rel", "item_id", "field_id",
        string="List columns",
        domain="[('model_id', '=', model_id), ('store', '=', True), "
               "('ttype', 'not in', ('one2many', 'many2many', 'binary'))]",
        help="Stored scalar fields displayed by an Individual records list.")
    list_field_order = fields.Json(
        default=lambda self: [],
        help="Technical field/column names in builder selection order. Many-to-many "
             "relations do not otherwise preserve display-column order; file sources "
             "store their selected parsed-column names here directly.")
    date_granularity = fields.Selection(
        [("minute", "Minute"), ("hour", "Hour"), ("day", "Day"), ("week", "Week"),
         ("month", "Month"), ("quarter", "Quarter"), ("year", "Year"),
         ("month_number", "Month (across years)")],
        default="month",
        help="Bucket size when grouping by a date field. 'Month' keeps the year "
             "(Jan 2024); 'Month (across years)' folds every January together.")
    domain = fields.Char(
        default="[]",
        help="A static filter for this item, on top of the data source filter.")
    record_limit = fields.Integer(
        default=0, help="Cap the number of groups (0 = no cap).")
    sort_mode = fields.Selection(
        [("default", "Default order"), ("value_desc", "Value: high to low"),
         ("value_asc", "Value: low to high"), ("label", "Label A to Z"),
         ("field", "By a specific field")],
        default="value_desc")
    sort_field_id = fields.Many2one(
        "ir.model.fields", string="Sort by field",
        domain="[('model_id', '=', model_id)]", ondelete="set null",
        help="Order groups by this field (used when sort is 'By a specific field').")
    sort_order = fields.Selection(
        [("asc", "Ascending"), ("desc", "Descending")], default="desc")
    include_archived = fields.Boolean(
        help="Include archived (inactive) records in this widget's data.")
    record_limit_visibility = fields.Boolean(
        help="When a row limit is set, also cap the record-count shown on click-through "
             "to that limit instead of the full match.")
    description = fields.Text(
        help="Free notes for this widget, shown on its info tooltip.")
    data_label_type = fields.Selection(
        [("value", "Value"), ("percent", "Percentage"), ("none", "Hidden")],
        default="value",
        help="What pie / doughnut slice labels show: the value, its share, or nothing.")
    chart_options = fields.Json(default=lambda self: {})
    conditional_rules = fields.Json(
        default=lambda self: [],
        help="Colour rules applied to values on tiles / lists / pivots: an ordered "
             "list of {measure, op, v1, v2, color, style} - first match wins.")
    color_mode = fields.Selection(
        [("theme", "Theme palette"), ("measure", "By measure"),
         ("category", "By category")], default="theme")
    # ---- display ----
    show_legend = fields.Boolean(default=True)
    show_values = fields.Boolean(default=True)
    show_grid = fields.Boolean(default=True)
    semi_circle = fields.Boolean(help="Render pie / doughnut as a half circle.")
    stacked = fields.Boolean(help="Stack series in a bar chart.")
    smooth = fields.Boolean(help="Smooth (curved) lines.")
    goal_value = fields.Float(help="Draw a horizontal goal line on a bar / line chart at this value.")
    combo_line = fields.Boolean(help="Overlay a cumulative running-total line (Pareto) on a bar chart.")
    # ---- advanced (data shaping) ----
    cumulative = fields.Boolean(
        help="Show a running total: each group adds to the ones before it.")
    fill_gaps = fields.Boolean(
        default=True,
        help="Fill empty periods in a date series with zero so lines never "
             "jump across missing months.")
    group_others = fields.Boolean(
        help="When a row cap is set, sum everything past it into a single "
             "'Others' group instead of dropping it.")
    # ---- actions ----
    click_action = fields.Selection(
        [("none", "Nothing"), ("records", "Open matching records"),
         ("drill", "Drill down a level"),
         ("dashboard", "Open another dashboard"),
         ("action", "Open an Odoo view/action")],
        default="records", help="What happens when a data point is clicked.")
    target_dashboard_id = fields.Many2one(
        "eh.board.dashboard", string="Target dashboard", ondelete="set null",
        help="Dashboard opened when click action is Open another dashboard.")
    window_action_id = fields.Many2one(
        "ir.actions.act_window", string="Window action", ondelete="set null",
        help="Existing Odoo list/pivot/graph action opened by this widget.")
    drill_field_id = fields.Many2one(
        "ir.model.fields", string="Drill into", ondelete="set null",
        help="Field to regroup by when drilling down.")
    # ---- per-item date filter ----
    date_filter_field_id = fields.Many2one(
        "ir.model.fields", string="Date field", ondelete="set null",
        help="Date field the dashboard date filter applies to for this widget.")
    default_date_filter = fields.Selection(
        [("none", "None"), ("today", "Today"), ("yesterday", "Yesterday"),
         ("tomorrow", "Tomorrow"), ("this_week", "This week"),
         ("last_week", "Last week"), ("next_week", "Next week"),
         ("this_month", "This month"), ("last_month", "Last month"),
         ("next_month", "Next month"), ("this_quarter", "This quarter"),
         ("last_quarter", "Last quarter"), ("next_quarter", "Next quarter"),
         ("this_year", "This year"), ("last_year", "Last year"),
         ("next_year", "Next year"), ("wtd", "Week to date"),
         ("mtd", "Month to date"), ("qtd", "Quarter to date"),
         ("ytd", "Year to date"), ("last_7", "Last 7 days"),
         ("last_30", "Last 30 days"), ("last_90", "Last 90 days"),
         ("last_365", "Last 365 days")],
        default="none",
        help="A built-in date range applied to this widget when the board's own "
             "date filter is off.")
    content = fields.Text(help="Body for text / to-do items.")
    icon = fields.Char(help="Font Awesome icon name for tiles/KPIs, e.g. fa-line-chart.")
    accent = fields.Selection(
        [("mint", "Mint"), ("blue", "Blue"), ("violet", "Violet"),
         ("amber", "Amber"), ("rose", "Rose"), ("teal", "Teal"),
         ("indigo", "Indigo"), ("slate", "Slate")],
        help="Accent colour for the widget (tiles use it as the fill).")
    tile_style = fields.Selection(
        [("soft", "Soft"), ("solid", "Solid"), ("outline", "Outline")],
        default="soft", help="Tile look: soft tint, solid fill, or outline.")
    show_trend = fields.Boolean(
        default=True, help="Show a period-over-period trend badge on KPIs when a date field is available.")
    default_geometry = fields.Json(
        default=lambda self: {}, help="Fallback grid position when no layout is active.")
    # copy=True so duplicating a widget carries its drill-down steps (One2many is
    # not copied by default), otherwise a cloned drill-enabled chart no longer drills.
    drill_ids = fields.One2many(
        "eh.board.drill", "item_id", string="Drill steps", copy=True)

    @api.constrains("click_action", "target_dashboard_id", "window_action_id",
                    "datasource_id")
    def _check_click_destination(self):
        for item in self:
            if (item.click_action == "dashboard" and item.target_dashboard_id
                    and item.target_dashboard_id == item.dashboard_id):
                raise ValidationError("A widget cannot navigate to its own dashboard.")
            if item.click_action == "action" and item.window_action_id:
                source_model = item.datasource_id.model_name if item.datasource_id else False
                if source_model and item.window_action_id.res_model != source_model:
                    raise ValidationError(
                        "The selected Odoo action must open the widget's source model.")

    _ACCENTS = ["mint", "blue", "violet", "amber", "rose", "teal", "indigo"]
    _DEFAULT_ICONS = {
        "tile": "fa-hashtag", "kpi": "fa-bullseye", "gauge": "fa-tachometer",
        "bar": "fa-bar-chart", "hbar": "fa-align-left", "column": "fa-bars",
        "line": "fa-line-chart", "area": "fa-area-chart", "pie": "fa-pie-chart",
        "doughnut": "fa-pie-chart", "list": "fa-table", "richtext": "fa-font",
        "todo": "fa-check-square-o",
    }

    @api.model
    def _sanitize_visual_vals(self, vals):
        """Bound JSON/CSS-facing configuration at its storage boundary.

        Builder UI validates these values, but templates, imports, XML data and
        direct RPC writes all reach this model too. Only strict hex colours and
        known conditional operators survive, preventing style injection and
        malformed JSON from breaking every renderer on a board.
        """
        vals = dict(vals or {})
        if "content" in vals:
            vals["content"] = html_sanitize(str(vals.get("content") or ""))
        for key, maximum in (("title", 200), ("subtitle", 500),
                             ("description", 20000)):
            if key in vals:
                vals[key] = str(vals.get(key) or "")[:maximum]
        if "icon" in vals:
            icon = str(vals.get("icon") or "")
            vals["icon"] = icon if re.fullmatch(r"fa-[a-z0-9-]{1,60}", icon) else False
        if "domain" in vals:
            vals["domain"] = str(vals.get("domain") or "[]")[:20000]
        if "record_limit" in vals:
            try:
                vals["record_limit"] = max(0, min(int(vals.get("record_limit") or 0), 10000))
            except (TypeError, ValueError):
                vals["record_limit"] = 0
        if "goal_value" in vals:
            try:
                goal = float(vals.get("goal_value") or 0.0)
            except (TypeError, ValueError):
                goal = 0.0
            vals["goal_value"] = goal if math.isfinite(goal) else 0.0
        if "list_field_order" in vals:
            order = vals.get("list_field_order")
            vals["list_field_order"] = [
                name for name in (order if isinstance(order, list) else [])
                if isinstance(name, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name)
            ][:12]
        if "chart_options" in vals:
            options = vals.get("chart_options")
            options = options if isinstance(options, dict) else {}
            colors = options.get("series_colors")
            vals["chart_options"] = {"series_colors": [
                color.lower() for color in (colors if isinstance(colors, list) else [])
                if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            ][:8]}
            if "slicer_display" in options:
                mode = options.get("slicer_display")
                vals["chart_options"]["slicer_display"] = (
                    mode if mode in ("auto", "list", "chips") else "auto")
        if "conditional_rules" in vals:
            rules = vals.get("conditional_rules")
            clean = []
            for rule in (rules if isinstance(rules, list) else [])[:32]:
                if not isinstance(rule, dict):
                    continue
                operator = rule.get("op")
                style = rule.get("style")
                color = str(rule.get("color") or "")
                if (operator not in {"gt", "gte", "lt", "lte", "eq", "ne", "between"}
                        or style not in {"text", "fill", "bar"}
                        or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
                    continue
                measure = rule.get("measure", "")
                if measure not in ("", None):
                    try:
                        measure = int(measure)
                    except (TypeError, ValueError):
                        continue
                    if measure < 0 or measure > 31:
                        continue
                    measure = str(measure)
                else:
                    measure = ""
                try:
                    value1 = float(rule.get("v1") or 0.0)
                    value2 = float(rule.get("v2") or 0.0)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value1) or not math.isfinite(value2):
                    continue
                clean_rule = {
                    "op": operator, "v1": value1, "v2": value2,
                    "color": color.lower(), "style": style,
                }
                # Keep legacy JSON stable when no explicit series was chosen.
                # Adding ``measure: ""`` broke exact round trips and bloated
                # every saved rule without changing its meaning.
                if measure:
                    clean_rule["measure"] = measure
                clean.append(clean_rule)
            vals["conditional_rules"] = clean
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._sanitize_visual_vals(vals) for vals in vals_list])

    def write(self, vals):
        # Sanitise rich-text / content at rest, so the value is already safe
        # everywhere it is later rendered (the in-canvas editor loads it into
        # innerHTML, and the PDF inlines it). Render-time sanitising in the item
        # type is kept as defence in depth.
        return super().write(self._sanitize_visual_vals(vals))

    def _resolved_accent(self):
        self.ensure_one()
        if self.accent:
            return self.accent
        return self._ACCENTS[(self.id or 0) % len(self._ACCENTS)]

    def _resolved_icon(self):
        self.ensure_one()
        return self.icon or self._DEFAULT_ICONS.get(self.item_type, "fa-th-large")

    def _meta(self):
        """Static descriptor for the grid + item chrome (no data query)."""
        # Only configured technical field definitions use sudo. Business reads
        # retain the viewer environment through datasource/item aggregation.
        self.ensure_one()
        item_type = get_item_type(self.item_type)
        geo = self.default_geometry or {}
        default_size = item_type.default_size if item_type else (4, 6)
        min_size = item_type.min_size if item_type else (2, 3)
        return {
            "id": self.id,
            "dashboard_id": self.dashboard_id.id,
            "type": self.item_type,
            "category": item_type.category if item_type else "chart",
            "component": item_type.component() if item_type else self.item_type,
            "title": self.title,
            "subtitle": self.subtitle,
            "color_mode": self.color_mode,
            "accent": self._resolved_accent(),
            "icon": self._resolved_icon(),
            "tile_style": self.tile_style or "soft",
            "chart_options": self.chart_options or {},
            "geometry": {
                "x": geo.get("x", 0), "y": geo.get("y", 0),
                "w": geo.get("w", default_size[0]), "h": geo.get("h", default_size[1]),
                "minW": min_size[0], "minH": min_size[1],
            },
            "drill": [d.spec() for d in self.drill_ids],
            "has_drill": bool(self.drill_ids),
            "model": self.datasource_id.model_name if self.datasource_id else None,
            "source_id": self.datasource_id.id if self._is_tabular() else None,
            "base_domain": self._click_base_domain(),
            "dimension": self.primary_column_id.name if self._is_tabular() and self.primary_column_id
            else self.primary_dimension_id.sudo().name if self.primary_dimension_id.sudo() else None,
            "dimension_type": self.primary_column_id.dtype if self._is_tabular() and self.primary_column_id
            else self.primary_dimension_id.sudo().ttype if self.primary_dimension_id.sudo() else None,
            "dimension_relation": self.primary_dimension_id.sudo().relation
            if self.primary_dimension_id.sudo() else None,
            "granularity": self.date_granularity,
            "click_action": self.click_action,
            "target_dashboard_id": self.target_dashboard_id.id
            if self.target_dashboard_id else False,
            "window_action_id": self.window_action_id.id
            if self.window_action_id else False,
            "record_limit": self.record_limit or 0,
            "record_limit_visibility": bool(self.record_limit_visibility),
            "description": self.description or "",
            "conditional_rules": self.conditional_rules or [],
            "display": {
                "show_legend": self.show_legend,
                "show_values": self.show_values,
                "show_grid": self.show_grid,
                "semi_circle": self.semi_circle,
                "stacked": self.stacked,
                "smooth": self.smooth,
                "goal_value": self.goal_value,
                "combo_line": self.combo_line,
                "data_label_type": self.data_label_type or "value",
            },
        }

    def _click_base_domain(self):
        """The widget's own static scope (data source + item filter), as a
        JSON-safe list, so a tile/mark click opens exactly the records behind
        the widget - not the whole model. Runtime filters (date range, board
        filters) are layered on at click time from the live options."""
        self.ensure_one()
        raw = (self.datasource_id.get_domain() if self.datasource_id else []) \
            + self._parse_domain(self.domain)
        out = []
        for leaf in raw:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3:
                out.append([leaf[0], leaf[1], leaf[2]])
            elif isinstance(leaf, str):
                out.append(leaf)
        return out

    # ------------------------------------------------------------------ spec
    def _parse_domain(self, raw):
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
        return list(parsed) if isinstance(parsed, (list, tuple)) else []

    def _runtime_domain(self, options):
        """Domain contributed by the runtime dashboard filter bar.

        A global date range scopes each item by its own date dimension when it
        has one, else by a standard date field on the model - so one date
        control re-scopes the whole board without per-item wiring.
        """
        options = options or {}
        domain = list(options.get("domain") or [])
        date_range = options.get("date_range") or {}
        start, end = date_range.get("start"), date_range.get("end")
        # The board's own date filter wins; when it is off, a widget can carry its
        # own built-in default range so it always opens pre-scoped.
        if not (start and end) and self.default_date_filter and self.default_date_filter != "none":
            own = self._preset_range(self.default_date_filter)
            if own:
                start, end = own
        if start and end:
            field = self._global_date_field()
            if field:
                domain += self._date_window_domain(field, start, end)
        # Global field filters re-scope every widget whose model has the field.
        domain += self._runtime_field_domain(options)
        return domain

    def _runtime_field_domain(self, options):
        """Only the board's FIELD filters (slicers / cross-filter), NOT the date
        range. A KPI trend compares two date windows itself, so it must honour
        active field filters without the board's date range clobbering the
        comparison period."""
        options = options or {}
        if self._is_tabular():
            known = set(self.datasource_id.column_ids.mapped("name"))
            return [(flt["field"], "in", flt["values"]) for flt in options.get("filters") or []
                    if flt.get("source_id") == self.datasource_id.id
                    and flt.get("field") in known and flt.get("values")]
        model = self.datasource_id.model_name if self.datasource_id else None
        model_fields = self.env[model]._fields if (model and model in self.env) else {}
        out = []
        for flt in options.get("filters") or []:
            if flt.get("source_id"):
                continue
            fname, values = flt.get("field"), flt.get("values")
            if not (fname and values and fname in model_fields):
                continue
            source_model = flt.get("model")
            source_relation = flt.get("relation")
            target = model_fields[fname]
            # Technical field names are not semantic identities. ``state`` on
            # sale.order must never filter account.move.state by accident. A
            # filter is portable only when both widgets use the same model, or
            # both fields are many2one links to the same comodel.
            same_model = not source_model or source_model == model
            same_relation = bool(
                source_relation and target.type == "many2one"
                and target.comodel_name == source_relation)
            if same_model or same_relation:
                out.append((fname, "in", values))
        return out

    def _date_window_domain(self, field_name, start, end):
        """Inclusive calendar-day range without truncating Datetime records.

        UI ranges are dates in viewer timezone. End boundary therefore becomes
        exclusive next midnight. For Datetime fields that local midnight is
        converted to UTC before building domain; for Date fields date strings
        stay timezone-free. This includes every record on final selected day.
        """
        self.ensure_one()
        try:
            start_date = fields.Date.to_date(start)
            end_date = fields.Date.to_date(end)
        except (TypeError, ValueError):
            return []
        if not start_date or not end_date:
            return []
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        model_name = self.datasource_id.model_name if self.datasource_id else None
        field = (self.env[model_name]._fields.get(field_name)
                 if model_name and model_name in self.env else None)
        if field and field.type == "datetime":
            tz_name = self.env.context.get("tz") or self.env.user.tz or "UTC"
            try:
                timezone = pytz.timezone(tz_name)
            except pytz.UnknownTimeZoneError:
                timezone = pytz.UTC

            def utc_midnight(day):
                try:
                    local = timezone.localize(
                        datetime.combine(day, time.min), is_dst=None)
                except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                    # A handful of zones move clocks at midnight. Pick standard
                    # side deterministically instead of crashing whole board.
                    local = timezone.localize(
                        datetime.combine(day, time.min), is_dst=False)
                return fields.Datetime.to_string(
                    local.astimezone(pytz.UTC).replace(tzinfo=None))

            return [
                (field_name, ">=", utc_midnight(start_date)),
                (field_name, "<", utc_midnight(end_date + timedelta(days=1))),
            ]
        return [
            (field_name, ">=", fields.Date.to_string(start_date)),
            (field_name, "<", fields.Date.to_string(end_date + timedelta(days=1))),
        ]

    def _effective_domain(self, options=None):
        """Exact domain used by aggregation, including runtime + drill scope."""
        self.ensure_one()
        options = options or {}
        ds = self.datasource_id
        domain = (ds.get_domain() if ds else []) \
            + self._parse_domain(self.domain) \
            + self._runtime_domain(options)
        drill = options.get("_drill") or {}
        if drill.get("dimension"):
            domain += list(drill.get("domain") or [])
        return domain

    def _json_domain(self, domain):
        """Convert domain leaves to RPC-safe values without changing meaning."""
        out = []
        for token in domain or []:
            if not (isinstance(token, (list, tuple)) and len(token) == 3):
                out.append(token)
                continue
            value = token[2]
            if isinstance(value, datetime):
                value = fields.Datetime.to_string(value)
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            elif isinstance(value, models.BaseModel):
                value = value.ids
            out.append([token[0], token[1], value])
        return out

    def _preset_range(self, preset):
        """Resolve a relative-date preset to a (start, end) date-string pair,
        mirroring the client filter bar so a per-widget default behaves exactly
        like the board's own date control."""
        from datetime import date
        from dateutil.relativedelta import relativedelta
        today = fields.Date.context_today(self)
        y, m = today.year, today.month

        def s(d):
            return fields.Date.to_string(d)

        if preset == "today":
            return s(today), s(today)
        if preset == "yesterday":
            day = today - relativedelta(days=1)
            return s(day), s(day)
        if preset == "tomorrow":
            day = today + relativedelta(days=1)
            return s(day), s(day)
        if preset == "this_week":
            start = today - relativedelta(days=today.weekday())
            return s(start), s(start + relativedelta(days=6))
        if preset == "wtd":
            return s(today - relativedelta(days=today.weekday())), s(today)
        if preset in ("last_week", "next_week"):
            this_monday = today - relativedelta(days=today.weekday())
            start = this_monday + relativedelta(
                days=-7 if preset == "last_week" else 7)
            return s(start), s(start + relativedelta(days=6))
        if preset == "this_month":
            start = date(y, m, 1)
            return s(start), s(start + relativedelta(months=1, days=-1))
        if preset == "mtd":
            return s(date(y, m, 1)), s(today)
        if preset == "this_quarter":
            q0 = ((m - 1) // 3) * 3 + 1
            start = date(y, q0, 1)
            return s(start), s(start + relativedelta(months=3, days=-1))
        if preset == "qtd":
            q0 = ((m - 1) // 3) * 3 + 1
            return s(date(y, q0, 1)), s(today)
        if preset == "this_year":
            return s(date(y, 1, 1)), s(date(y, 12, 31))
        if preset == "ytd":
            return s(date(y, 1, 1)), s(today)
        if preset == "last_month":
            first = date(y, m, 1)
            last_prev = first - relativedelta(days=1)
            return s(date(last_prev.year, last_prev.month, 1)), s(last_prev)
        if preset == "next_month":
            start = date(y, m, 1) + relativedelta(months=1)
            return s(start), s(start + relativedelta(months=1, days=-1))
        if preset in ("last_quarter", "next_quarter"):
            q0 = date(y, ((m - 1) // 3) * 3 + 1, 1)
            start = q0 + relativedelta(
                months=-3 if preset == "last_quarter" else 3)
            return s(start), s(start + relativedelta(months=3, days=-1))
        if preset == "last_year":
            return s(date(y - 1, 1, 1)), s(date(y - 1, 12, 31))
        if preset == "next_year":
            return s(date(y + 1, 1, 1)), s(date(y + 1, 12, 31))
        if preset == "last_7":
            return s(today - relativedelta(days=6)), s(today)
        if preset == "last_30":
            return s(today - relativedelta(days=29)), s(today)
        if preset == "last_90":
            return s(today - relativedelta(days=89)), s(today)
        if preset == "last_365":
            return s(today - relativedelta(days=364)), s(today)
        return None

    def _global_date_field(self):
        self.ensure_one()
        if self._is_tabular():
            dates = self.datasource_id.column_ids.filtered(lambda c: c.dtype == "date")
            if self.primary_column_id in dates:
                return self.primary_column_id.name
            return dates.name if len(dates) == 1 else None
        if self.date_filter_field_id.sudo():
            return self.date_filter_field_id.sudo().name
        if (self.primary_dimension_id.sudo()
                and self.primary_dimension_id.sudo().ttype in ("date", "datetime")):
            return self.primary_dimension_id.sudo().name
        model = self.datasource_id.model_name if self.datasource_id else None
        if model and model in self.env:
            fields = self.env[model]._fields
            for candidate in ("date", "date_order", "invoice_date", "create_date"):
                if candidate in fields:
                    return candidate
        return None

    def _dimension(self, field):
        if not field:
            return None
        gran = self.date_granularity if field.ttype in ("date", "datetime") else None
        return {"field": field.name, "granularity": gran}

    def _is_tabular(self):
        """True when the data source is a column-based (file / REST) provider."""
        ds = self.datasource_id
        prov = get_datasource(ds.provider_type) if ds else None
        return bool(prov and getattr(prov, "tabular", False))

    def _tabular_dimension(self, column):
        """Group-by dict for a parsed source column."""
        if not column:
            return None
        gran = self.date_granularity if column.dtype == "date" else None
        return {"field": column.name, "granularity": gran, "dtype": column.dtype}

    def _tabular_dimension_name(self, name):
        """Resolve a column name on this source to a group-by dict (drill)."""
        if not name or not self.datasource_id:
            return None
        col = self.datasource_id.column_ids.filtered(lambda c: c.name == name)[:1]
        return self._tabular_dimension(col) if col else None

    def _decomp_fields(self):
        """Ordered field-name chain for the decomposition tree: the primary
        dimension, then each drill step. Each level breaks the one above down."""
        self.ensure_one()
        chain = []
        if self.primary_dimension_id.sudo():
            chain.append(self.primary_dimension_id.sudo().name)
        for step in self.drill_ids:
            if step.field_name and step.field_name not in chain:
                chain.append(step.field_name)
        return chain

    def _decomp_labels(self):
        self.ensure_one()
        out = []
        if self.primary_dimension_id.sudo():
            out.append(self.primary_dimension_id.sudo().field_description or self.primary_dimension_id.sudo().name)
        for step in self.drill_ids:
            f = step.field_id.sudo()
            if f:
                out.append(f.field_description or f.name)
        return out

    def get_decomp(self, path=None, options=None):
        """One level of a decomposition tree: break the measure down by the next
        field in the chain, scoped to the clicked ``path`` (list of {field,
        value}). Returns the child nodes sorted by value, biggest first."""
        self.ensure_one()
        path = path or []
        options = dict(options or {})
        chain = self._decomp_fields()
        depth = len(path)
        if depth >= len(chain) or not self.datasource_id:
            return {"nodes": [], "leaf": True, "total": 0}
        field = chain[depth]
        extra = [(p["field"], "=", p.get("value") if p.get("value") not in (None, False) else False)
                 for p in path if p.get("field")]
        options["_drill"] = {"dimension": field, "domain": extra, "sort": "value_desc", "limit": 30}
        spec = self._resolve_spec(options)
        provider = get_datasource(self.datasource_id.provider_type)
        try:
            result = provider.aggregate(self.datasource_id, spec)
        except Exception as err:  # noqa: BLE001 - surfaced to the widget
            return {"nodes": [], "leaf": True, "total": 0, "error": str(err)}
        rows = result.get("rows", [])
        keys = result.get("measures", [])
        mk = keys[0] if keys else None
        # True total across ALL groups at this level, not just the top `limit`
        # shown - otherwise the root value and every node percentage understate
        # the measure whenever there are more groups than the display cap.
        total = 0
        if mk:
            total_spec = dict(spec)
            total_spec["dimensions"] = []
            total_spec["limit"] = None
            total_spec["read_cap"] = None
            try:
                trows = provider.aggregate(self.datasource_id, total_spec).get("rows", [])
                total = trows[0]["values"].get(mk, 0) if trows else 0
            except Exception:  # noqa: BLE001 - fall back to the shown-rows sum
                total = sum(r["values"].get(mk, 0) for r in rows)
        nodes = [{
            "field": field,
            "label": (r.get("labels") or [""])[0] or "None",
            "value": r["values"].get(mk, 0) if mk else 0,
            "key": (r.get("keys") or [None])[0],
            "pct": ((r["values"].get(mk, 0) / total * 100) if (total and mk) else 0),
        } for r in rows]
        return {"nodes": nodes, "field": field, "leaf": depth + 1 >= len(chain), "total": total}

    def _dimension_name(self, name):
        """Resolve a stored field name on this item's model to a dimension dict."""
        if not name or not self.datasource_id:
            return None
        field = self.env["ir.model.fields"].sudo().search(
            [("model_id", "=", self.datasource_id.model_id.id), ("name", "=", name)],
            limit=1)
        return self._dimension(field) if field else None

    def _resolve_spec(self, options=None, no_dimension=False):
        self.ensure_one()
        options = options or {}
        ds = self.datasource_id
        domain = self._effective_domain(options)
        tabular = self._is_tabular()
        # Drill override: regroup by the drilled field and narrow to the path
        # the user clicked through (set by get_drilled_payload).
        drill = options.get("_drill") or {}
        dimensions = []
        if drill.get("dimension"):
            dim = (self._tabular_dimension_name(drill["dimension"]) if tabular
                   else self._dimension_name(drill["dimension"]))
            if dim:
                dimensions.append(dim)
        elif not no_dimension and tabular:
            for col in (self.primary_column_id, self.secondary_column_id):
                dim = self._tabular_dimension(col)
                if dim:
                    dimensions.append(dim)
        elif not no_dimension:
            for field in (self.primary_dimension_id.sudo(), self.secondary_dimension_id.sudo()):
                dim = self._dimension(field)
                if dim:
                    dimensions.append(dim)
        measures, labels, formulas, line_measures = [], {}, [], []
        formats, units, currencies = {}, {}, {}
        for m in self.measure_ids:
            key = m.measure_key()
            m_field = m.column_id.name if (tabular and m.column_id) else m.field_name
            labels[key] = m.name or (m.column_id.label if m.column_id else False) \
                or m.field_name or key
            formats[key] = m.number_format or "compact"
            units[key] = m.unit or ""
            if m.currency_id:
                currencies[key] = {
                    "id": m.currency_id.id,
                    "code": m.currency_id.name,
                    "symbol": m.currency_id.symbol or m.currency_id.name,
                    "position": m.currency_id.position or "before",
                    "decimal_places": m.currency_id.decimal_places,
                }
            if m.as_line:
                line_measures.append(key)
            if m.aggregate == "formula":
                formulas.append({"key": key, "formula": m.formula or "0"})
            else:
                measures.append({
                    "key": key,
                    "field": m_field or None,
                    "verb": m.aggregate,
                    "multiplier": m.multiplier or 1.0,
                })
        return {
            "model": ds.model_name if ds else None,
            "domain": domain,
            "dimensions": dimensions,
            "measures": measures,
            "measure_keys": [m["key"] for m in measures],
            "formula_measures": formulas,
            "line_measures": line_measures,
            "base_measure_keys": [m["key"] for m in measures],
            "all_measure_keys": [m.measure_key() for m in self.measure_ids],
            "measure_labels": labels,
            "measure_formats": formats,
            "measure_units": units,
            "measure_currencies": currencies,
            "number_format": (self.measure_ids[:1].number_format or "compact")
            if self.measure_ids else "compact",
            "unit": (self.measure_ids[:1].unit or "") if self.measure_ids else "",
            "currency": currencies.get(self.measure_ids[:1].measure_key())
            if self.measure_ids else None,
            "company_ids": options.get("company_ids"),
            "sort": drill.get("sort") or self.sort_mode or "default",
            "order": self._order_clause(),
            "limit": drill.get("limit") or (self.record_limit or None),
            "group_others": self.group_others,
            "cumulative": self.cumulative,
            "fill_gaps": self.fill_gaps,
            "include_archived": self.include_archived,
            "data_label_type": self.data_label_type or "value",
            "measure_calculations": {
                m.measure_key(): (m.table_calculation or "none")
                for m in self.measure_ids
                if (m.table_calculation or "none") != "none"
            },
            # The percentage column means different things for an additive
            # aggregate (a share of the total) and a non-additive one (a ratio
            # against the total-grain average / min / max). The label has to say
            # which, so it needs the aggregate.
            "measure_aggregates": {
                m.measure_key(): (m.aggregate or "sum")
                for m in self.measure_ids
                if (m.table_calculation or "none") != "none"
            },
            "item_id": self.id,
        }

    def _resolve_record_list_spec(self, options=None):
        """Bounded, record-rule-safe spec for an ungrouped list.

        Field records are relational configuration, not arbitrary client names.
        Provider still validates them against live model metadata before reading.
        """
        self.ensure_one()
        options = options or {}
        ds = self.datasource_id
        domain = self._effective_domain(options)
        fields_spec = []
        if not ds:
            return {
                "model": None, "domain": domain, "fields": [], "order": "id desc",
                "limit": self.record_limit or 50,
                "company_ids": options.get("company_ids"),
                "include_archived": self.include_archived,
            }
        if self._is_tabular():
            columns = {column.name: column for column in ds.column_ids}
            for name in (self.list_field_order or [])[:12]:
                column = columns.get(name)
                if column:
                    fields_spec.append({
                        "name": column.name,
                        "label": column.label or column.name,
                        "type": {
                            "number": "float", "date": "date", "bool": "boolean",
                        }.get(column.dtype, "char"),
                    })
        else:
            for field in self._ordered_list_fields()[:12]:
                if (field.model_id == ds.model_id and field.store \
                        and field.ttype not in ("one2many", "many2many", "binary")):
                    fields_spec.append({
                        "name": field.name,
                        "label": field.field_description or field.name,
                        "type": field.ttype,
                    })
        order = "id desc"
        if (self.sort_field_id.sudo() and self.sort_field_id.sudo().model_id == ds.model_id
                and self.sort_field_id.sudo().store
                and self.sort_field_id.sudo().ttype not in ("one2many", "many2many", "binary")):
            order = "%s %s, id %s" % (
                self.sort_field_id.sudo().name,
                "desc" if self.sort_order == "desc" else "asc",
                "desc" if self.sort_order == "desc" else "asc")
        return {
            "model": ds.model_name if ds else None,
            "domain": domain,
            "fields": fields_spec,
            "order": order,
            "limit": self.record_limit or 50,
            "company_ids": options.get("company_ids"),
            "include_archived": self.include_archived,
            "item_id": self.id,
        }

    def _ordered_list_fields(self):
        """Selected columns in explicit builder order, then safe fallback order."""
        self.ensure_one()
        by_name = {field.name: field for field in self.sudo().list_field_ids}
        ordered_ids = []
        seen = set()
        for name in self.list_field_order or []:
            if name in by_name and name not in seen:
                ordered_ids.append(by_name[name].id)
                seen.add(name)
        for field in self.sudo().list_field_ids:
            if field.name not in seen:
                ordered_ids.append(field.id)
                seen.add(field.name)
        return self.env["ir.model.fields"].sudo().browse(ordered_ids)

    def _order_clause(self):
        """A real SQL-style order string when the user pins sorting to a GROUPED
        field; None otherwise (aggregation then applies value/label sorting).

        ``_read_group`` only accepts an order term that is one of the group-by
        dimensions (or an aggregate). A bare non-grouped field raises ValueError,
        so we restrict field-sort to the dimensions actually grouped."""
        self.ensure_one()
        if self.sort_mode == "field" and self.sort_field_id.sudo():
            name = self.sort_field_id.sudo().name
            grouped = {
                self.primary_dimension_id.sudo().name if self.primary_dimension_id.sudo() else None: self.primary_dimension_id.sudo(),
                self.secondary_dimension_id.sudo().name if self.secondary_dimension_id.sudo() else None: self.secondary_dimension_id.sudo(),
            }
            if name in grouped and grouped[name]:
                direction = "desc" if self.sort_order == "desc" else "asc"
                fld = grouped[name]
                # A date/datetime dimension is grouped as "field:granularity"; the
                # order term must reference that exact spec, not the bare field, or
                # _read_group raises ValueError on Odoo 17+ and the widget errors.
                if fld.ttype in ("date", "datetime"):
                    from ..lib.aggregation import _safe_granularity
                    gran = _safe_granularity(self.date_granularity or "month")
                    return "%s:%s %s" % (name, gran, direction)
                return "%s %s" % (name, direction)
        return None

    def _resolve_comparison(self, options, value):
        """Date-effective target plus live period comparison for KPI/gauge."""
        self.ensure_one()
        measure = self.measure_ids[:1]
        out = {}
        date_range = (options or {}).get("date_range") or {}
        target_anchor = date_range.get("end") or fields.Date.context_today(self)
        if measure and (measure.target_value or measure.target_schedule):
            target = measure.target_at(target_anchor)
            out["target"] = target
            out["achievement"] = (value / target) if target else 0.0
        if self.show_trend:
            out.update(self._compute_trend(options))
        return out

    def _compute_trend(self, options):
        """Period-over-period delta for a KPI: current window vs the previous
        equal-length window. Uses the item's date field; silent when there is
        none. Also returns a small spark series so the tile feels alive."""
        self.ensure_one()
        from datetime import timedelta
        from dateutil.relativedelta import relativedelta
        field = self._global_date_field()
        measure = self.measure_ids[:1]
        if not field or not measure or not self.datasource_id:
            return {}
        today = fields.Date.context_today(self)
        date_range = (options or {}).get("date_range") or {}
        if date_range.get("start") and date_range.get("end"):
            start = fields.Date.to_date(date_range["start"])
            end = fields.Date.to_date(date_range["end"])
        else:
            end = today
            start = today - timedelta(days=29)
        span = max(1, (end - start).days + 1)
        # Honour the measure's comparison mode: "same period last year" shifts
        # the exact window back a year; "previous period" uses the abutting
        # equal-length window; "none" shows only the sparkline, no delta.
        mode = measure.compare_mode or "prev_period"
        if mode == "none":
            return {"spark": self._spark_series(field, start, end, options)}
        if mode == "prev_year":
            prev_start = start - relativedelta(years=1)
            prev_end = end - relativedelta(years=1)
        else:
            prev_end = start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=span - 1)
        cur = self._window_total(field, start, end, options)
        prev = self._window_total(field, prev_start, prev_end, options)
        out = {"spark": self._spark_series(field, start, end, options)}
        if prev:
            out["trend"] = (cur - prev) / abs(prev)
            out["trend_prev"] = prev
            out["trend_current"] = cur
        return out

    def _window_total(self, field, start, end, options=None):
        spec = self._resolve_spec(no_dimension=True)
        # Honour the board's active field filters so the trend measures the same
        # population as the headline value it sits under (the date range is the
        # window itself, applied explicitly below - not from the runtime domain).
        spec["domain"] = spec["domain"] + self._runtime_field_domain(options) \
            + self._date_window_domain(field, start, end)
        provider = get_datasource(self.datasource_id.provider_type)
        result = provider.aggregate(self.datasource_id, spec)
        rows = result.get("rows", [])
        keys = result.get("measures", [])
        if rows and keys:
            return rows[0]["values"].get(keys[0], 0.0)
        return 0.0

    def _spark_series(self, field, start, end, options=None):
        """A tiny daily/weekly series over the window for the tile sparkline."""
        spec = self._resolve_spec(no_dimension=True)
        spec["domain"] = spec["domain"] + self._runtime_field_domain(options) \
            + self._date_window_domain(field, start, end)
        gran = "day" if (end - start).days <= 45 else "week"
        spec["dimensions"] = [{"field": field, "granularity": gran}]
        provider = get_datasource(self.datasource_id.provider_type)
        result = provider.aggregate(self.datasource_id, spec)
        from ..lib import aggregation
        rows = aggregation.fill_time_gaps(result.get("rows", []), gran)
        keys = result.get("measures", [])
        if not keys:
            return []
        return [r["values"].get(keys[0], 0.0) for r in rows][-24:]

    def _headline_value(self, options=None):
        """Compute the first measure at full scope, not the sum of chart groups.

        Averages, distinct counts and formulas must be recomputed at total
        grain. SQL/join shapes do not expose a general scalar contract; only
        their explicitly configured headline widgets have defined semantics.
        """
        self.ensure_one()
        source = self.datasource_id
        if not source:
            return None
        if source.provider_type in ("join", "sql"):
            if self.item_type not in ("tile", "kpi", "gauge", "bullet"):
                return None
            payload = self.get_payload(options or {})
            return None if payload.get("error") else payload.get("value")
        from ..items.standard import apply_formulas
        spec = self._resolve_spec(options, no_dimension=True)
        spec.update({"dimensions": [], "limit": None, "read_cap": None,
                     "sort": "default", "order": None, "group_others": False,
                     "cumulative": False, "fill_gaps": False})
        try:
            result = apply_formulas(spec, get_datasource(source.provider_type).aggregate(source, spec))
            if result.get("error"):
                return None
            keys = result.get("measures") or []
            rows = result.get("rows") or []
            if not keys:
                return None
            value = rows[0]["values"].get(keys[0], 0.0) if rows else 0.0
            return float(value) if math.isfinite(float(value)) else None
        except Exception:  # an unavailable metric must never become a zero alert
            return None

    def _insight_text(self, options=None, payload=None):
        """A plain-language read of this widget's numbers - the top mover, the
        share, the trend vs target. Deterministic and offline, so it always
        works; a BYO-key LLM can enrich it through the same seam later."""
        self.ensure_one()
        payload = payload if payload is not None else self.get_payload(options or {})
        if payload.get("error") or payload.get("category") == "content":
            return None
        fmt = payload.get("number_format", "compact")
        dash = self.dashboard_id

        def num(v):
            return dash._fmt_num(v, fmt)

        if payload.get("category") == "kpi":
            parts = ["%s is %s." % (self.title or "This KPI", num(payload.get("value", 0)))]
            if payload.get("target"):
                pct = (payload.get("achievement") or 0) * 100
                parts.append("That is %.0f%% of the %s target." % (pct, num(payload["target"])))
            if payload.get("trend") is not None:
                direction = "up" if payload["trend"] >= 0 else "down"
                parts.append("%s %.0f%% versus the previous period."
                             % (direction, abs(payload["trend"] * 100)))
            return " ".join(parts)

        rows = payload.get("rows") or []
        keys = payload.get("measure_keys") or []
        if rows and keys:
            k = keys[0]
            top = max(rows, key=lambda r: r["values"].get(k, 0))
            label = (top.get("labels") or [""])[0] or "The top group"
            topval = top["values"].get(k, 0)
            # A "% of total" share is only meaningful for an ADDITIVE measure
            # (sum / count); summing per-group averages/mins/maxes is nonsense. And
            # the sum is of the SHOWN groups (a row cap may drop the tail), so say
            # "shown" rather than implying it is the grand total.
            verb = (self.measure_ids[:1].aggregate if self.measure_ids else "sum") or "sum"
            if verb in ("sum", "count"):
                total = sum(r["values"].get(k, 0) for r in rows)
                share = (topval / total * 100) if total else 0
                return ("%s leads at %s, %.0f%% of the %s shown across %d groups."
                        % (label, num(topval), share, num(total), len(rows)))
            measure_name = (self.measure_ids[:1].name or "value") if self.measure_ids else "value"
            return ("%s has the highest %s at %s across %d groups."
                    % (label, measure_name, num(topval), len(rows)))
        return None

    def _influencer_text(self, options=None):
        """Key-influencers-lite: which single group drives this widget's measure
        the most. Offline + deterministic; groups the measure by a candidate
        field and reports the top contributor's share."""
        self.ensure_one()
        if not self.datasource_id or not self.measure_ids:
            return None
        if self.measure_ids[:1].aggregate not in ("count", "sum"):
            return None
        field = self.primary_dimension_id.sudo()
        if not field:
            model = self.datasource_id.model_id
            field = self.env["ir.model.fields"].sudo().search([
                ("model_id", "=", model.id), ("store", "=", True),
                ("ttype", "in", ("many2one", "selection")),
                ("name", "not in", ("create_uid", "write_uid", "company_id")),
            ], limit=1)
        if not field:
            return None
        spec = self._resolve_spec(options, no_dimension=True)
        spec["dimensions"] = [{"field": field.name, "granularity": None}]
        spec["limit"] = None
        provider = get_datasource(self.datasource_id.provider_type)
        try:
            result = provider.aggregate(self.datasource_id, spec)
        except Exception:  # noqa: BLE001 - insight must never crash the dialog
            return None
        rows = result.get("rows", [])
        keys = result.get("measures", [])
        if not rows or not keys:
            return None
        k = keys[0]
        total = sum(r["values"].get(k, 0) for r in rows)
        if not total:
            return None
        top = max(rows, key=lambda r: r["values"].get(k, 0))
        label = (top.get("labels") or [""])[0] or "one group"
        share = top["values"].get(k, 0) / total * 100
        measure_name = self.measure_ids[:1].name or "the total"
        return ("Top contributor: %s is %.0f%% of %s across %d groups."
                % (label, share, measure_name, len(rows)))

    def _snapshot_history(self, limit=60):
        """Recorded historical values for this already-authorised widget.

        Snapshot rows deliberately have no direct Viewer ACL: raw historical
        figures must not be browsable as a standalone model.  Rendering starts
        from an item the caller passed record rules for, so sudo is restricted
        to that exact item id and cannot expose another board's history.
        """
        self.ensure_one()
        limit = max(1, min(int(limit or 60), 365))
        snaps = self.env["eh.board.snapshot"].sudo().search(
            [("item_id", "=", self.id)], order="captured_on desc", limit=limit)
        snaps = reversed(snaps)
        return [{"date": fields.Datetime.to_string(s.captured_on), "value": s.value}
                for s in snaps]

    # --------------------------------------------------------------- payload
    def get_payload(self, options=None):
        """Resolve this item to a JSON payload for its OWL component.

        Delegates entirely to the registered item type. Validation problems and
        runtime errors are returned as an ``error`` string so the widget can
        explain itself inline rather than rendering a silent blank.
        """
        self.ensure_one()
        item_type = get_item_type(self.item_type)
        if not item_type:
            return {"id": self.id, "error": "Unknown item type %r" % self.item_type}
        problems = item_type.validate(self)
        if problems:
            return {"id": self.id, "type": self.item_type,
                    "title": self.title, "error": " ".join(problems)}
        try:
            payload = item_type.build(self, options or {})
        except Exception as err:  # noqa: BLE001 - surfaced to the widget, not swallowed
            payload = {"type": self.item_type, "error": str(err)}
        payload.setdefault("id", self.id)
        payload["id"] = self.id
        payload["title"] = self.title
        payload["subtitle"] = self.subtitle
        if self.datasource_id.provider_type in ("sheets", "rest"):
            payload["source_status"] = self.datasource_id._remote_status()
        payload["effective_domain"] = self._json_domain(
            self._effective_domain(options or {}))
        return payload

    def _drill_options(self, path=None, options=None):
        """Resolve only configured, ordered drill steps; retain active filters."""
        self.ensure_one()
        options = dict(options or {})
        options.pop("_drill", None)
        path = [] if path is None else path
        if not isinstance(path, list) or len(path) > 10:
            raise UserError(_("Dashboard drill path is invalid."))
        if not path:
            return options
        steps = self.drill_ids
        if len(path) > len(steps):
            raise UserError(_("This drill path is no longer available. Refresh the dashboard and drill again."))
        primary = self.primary_column_id.name if self._is_tabular() else self.primary_dimension_id.sudo().name
        chain = [primary] + steps.mapped("field_name")
        extra = []
        for index, part in enumerate(path):
            if (not isinstance(part, dict) or part.get("field") != chain[index]
                    or isinstance(part.get("value"), (dict, list))):
                raise UserError(_("Dashboard drill path is invalid."))
            value = part.get("value")
            extra.append((part["field"], "=", value if value not in (None, False) else False))
        step = steps[len(path) - 1]
        options["_drill"] = {"dimension": step.field_name, "domain": extra,
                             "sort": step.sort or None, "limit": step.limit or None}
        return options

    def get_drilled_payload(self, path=None, options=None):
        """Payload for one drill level: regroup by the configured drill field,
        scoped to the values the user clicked through (``path``).

        ``path`` is an ordered list of ``{field, value, label}`` clicks. Depth 0
        (empty path) is the normal widget; each step advances to the matching
        ``drill_ids`` field with the accumulated click domain and any per-step
        chart type / sort / limit. Stale paths are rejected instead of widened.
        """
        self.ensure_one()
        path = path or []
        options = self._drill_options(path, options)
        steps = self.drill_ids
        depth = len(path)
        if depth == 0 or depth > len(steps):
            return self.get_payload(options)
        step = steps[depth - 1]
        item_type = get_item_type(step.chart_type or self.item_type)
        if not item_type:
            return self.get_payload(options)
        try:
            payload = item_type.build(self, options)
        except Exception as err:  # noqa: BLE001 - surfaced to the widget
            payload = {"type": step.chart_type or self.item_type, "error": str(err)}
        payload["id"] = self.id
        payload["title"] = self.title
        payload["subtitle"] = self.subtitle
        payload["component"] = item_type.component()
        payload["category"] = item_type.category
        payload["drill_depth"] = depth
        if self.datasource_id.provider_type in ("sheets", "rest"):
            payload["source_status"] = self.datasource_id._remote_status()
        payload["effective_domain"] = self._json_domain(
            self._effective_domain(options))
        return payload
