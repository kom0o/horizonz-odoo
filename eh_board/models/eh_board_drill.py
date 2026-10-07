# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
from odoo import fields, models


class EhBoardDrill(models.Model):
    """One step in an item's drill-down chain.

    Each step re-groups by a different field and may narrow the chart type,
    sort and limit. Clicking a data point pushes the clicked value onto the
    domain and advances to the next step; the breadcrumb walks back up.
    """
    _name = "eh.board.drill"
    _description = "Dashboard Drill Step"
    _order = "item_id, sequence, id"

    item_id = fields.Many2one(
        "eh.board.item", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    field_id = fields.Many2one(
        "ir.model.fields", string="Group by", required=True, ondelete="cascade")
    field_name = fields.Char(related="field_id.name", store=True)
    chart_type = fields.Selection(
        selection="_chart_type_selection",
        help="Chart type to switch to at this level (blank keeps the current).")
    sort = fields.Selection(
        [("value_desc", "Value (high to low)"), ("value_asc", "Value (low to high)"),
         ("label", "Label")], default="value_desc")
    limit = fields.Integer(default=0)
    propagate_domain = fields.Boolean(default=True)

    def _chart_type_selection(self):
        from ..lib.registry import item_type_selection
        return [("", "Keep current")] + item_type_selection()

    def spec(self):
        self.ensure_one()
        return {
            "field": self.field_name,
            "chart_type": self.chart_type or None,
            "sort": self.sort,
            "limit": self.limit or None,
            "propagate": self.propagate_domain,
        }
