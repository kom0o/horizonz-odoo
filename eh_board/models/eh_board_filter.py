# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
from odoo import fields, models

# Relative-date presets exposed on the global filter bar. The resolution to an
# actual date window happens on the client so it always reflects the viewer's
# timezone; the server only needs to know which preset was chosen.
DATE_PRESETS = [
    ("today", "Today"), ("yesterday", "Yesterday"),
    ("tomorrow", "Tomorrow"),
    ("this_week", "This Week"), ("last_week", "Last Week"),
    ("next_week", "Next Week"),
    ("this_month", "This Month"), ("last_month", "Last Month"),
    ("next_month", "Next Month"),
    ("this_quarter", "This Quarter"), ("last_quarter", "Last Quarter"),
    ("next_quarter", "Next Quarter"),
    ("this_year", "This Year"), ("last_year", "Last Year"),
    ("next_year", "Next Year"),
    ("last_7", "Last 7 Days"), ("last_30", "Last 30 Days"),
    ("last_90", "Last 90 Days"), ("last_365", "Last 365 Days"),
    ("ytd", "Year to Date"), ("qtd", "Quarter to Date"),
    ("mtd", "Month to Date"), ("custom", "Custom Range"),
]


class EhBoardFilter(models.Model):
    _name = "eh.board.filter"
    _description = "Dashboard Filter"
    _order = "sequence, id"

    dashboard_id = fields.Many2one(
        "eh.board.dashboard", required=True, ondelete="cascade", index=True)
    item_id = fields.Many2one(
        "eh.board.item", ondelete="cascade",
        help="Leave empty for a global filter shown on the dashboard bar.")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    filter_type = fields.Selection(
        [("date", "Date"), ("field", "Field")],
        required=True, default="date")
    field_id = fields.Many2one(
        "ir.model.fields", string="Field", ondelete="cascade")
    field_name = fields.Char(related="field_id.name", store=True)
    date_preset = fields.Selection(DATE_PRESETS, default="this_month")
    default_value = fields.Json(default=lambda self: {})
    options = fields.Json(default=lambda self: {})

    def spec(self):
        """Client-side descriptor for the filter bar (with option values)."""
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "type": self.filter_type,
            "field": self.field_name,
            "ttype": self.field_id.sudo().ttype if self.field_id.sudo() else None,
            "model": self.field_id.sudo().model_id.model if self.field_id.sudo() else None,
            "relation": self.field_id.sudo().relation if self.field_id.sudo() else None,
            "date_preset": self.date_preset,
            "default": self.default_value or {},
            "options": self.get_options() if self.filter_type == "field" else [],
            "global": not self.item_id,
        }

    def get_options(self, limit=200):
        """Value choices for a field filter: related records for a many2one,
        the selection list for a selection field, else distinct stored values."""
        self.ensure_one()
        field = self.field_id.sudo()
        if not field:
            return []
        if field.ttype == "many2one" and field.relation:
            records = self.env[field.relation].search([], limit=limit)
            return [{"value": r.id, "label": r.display_name} for r in records]
        model = field.model_id.model
        if model not in self.env:
            return []
        Model = self.env[model]
        if field.ttype == "selection":
            try:
                sels = Model.fields_get([field.name])[field.name].get("selection", [])
            except Exception:  # noqa: BLE001
                sels = []
            return [{"value": v, "label": lbl} for v, lbl in sels]
        if field.ttype == "boolean":
            # Both values are real choices; the distinct-value scan below drops
            # False (treated as "no value"), so the user could never filter for it.
            return [{"value": True, "label": "Yes"}, {"value": False, "label": "No"}]
        # distinct stored values (char / integer) - bounded so a high-cardinality
        # field cannot pull the whole table into a filter.
        from ..lib import aggregation
        rows = aggregation.grouped_read(Model, [], [field.name], [], limit=limit)
        out = []
        for row in rows:
            val = row[0]
            if val is None or val is False:
                continue
            if hasattr(val, "display_name"):
                out.append({"value": val.id, "label": val.display_name})
            else:
                out.append({"value": val, "label": str(val)})
        return out[:limit]
