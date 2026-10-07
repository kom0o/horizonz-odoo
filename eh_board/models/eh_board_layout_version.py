# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
from odoo import fields, models


class EhBoardLayoutVersion(models.Model):
    """The single, coherent layout persistence.

    One JSON grid map per version - not the three-way ``Char`` + ``Json`` +
    child-record split the incumbents carry. Versions give per-company variants
    and rollback lineage for free.
    """
    _name = "eh.board.layout.version"
    _description = "Dashboard Layout Version"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, default="Default")
    dashboard_id = fields.Many2one(
        "eh.board.dashboard", required=True, ondelete="cascade", index=True)
    is_active = fields.Boolean(default=True)
    is_default = fields.Boolean()
    company_id = fields.Many2one("res.company")
    grid = fields.Json(
        default=lambda self: {},
        help="Map of item id -> {x, y, w, h, minW, minH} on the 12-column grid.")
    density = fields.Selection(
        [("comfortable", "Comfortable"), ("compact", "Compact")],
        default="comfortable")
    parent_id = fields.Many2one(
        "eh.board.layout.version", string="Rolled back from", ondelete="set null")
