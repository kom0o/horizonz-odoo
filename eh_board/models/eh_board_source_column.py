# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Column registry for tabular (file / REST) data sources.

This is the elegant mirror of the incumbent's per-file column list, but WITHOUT
polluting ``ir.model`` / ``ir.model.fields`` or creating a physical table. Each
detected column is one lightweight row scoped to its data source and rebuilt on
every (re)upload - a delete+create of THIS source's children only, so there is
no global scratch table and no cross-user race.
"""
from odoo import api, fields, models


class EhBoardSourceColumn(models.Model):
    _name = "eh.board.source.column"
    _description = "Dashboard Source Column"
    _order = "datasource_id, sequence, id"

    datasource_id = fields.Many2one(
        "eh.board.datasource", string="Data Source",
        required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, help="Technical column key used in the spec.")
    label = fields.Char(required=True, help="Human header shown in pickers.")
    dtype = fields.Selection(
        [("number", "Number"), ("date", "Date"), ("bool", "Boolean"), ("text", "Text")],
        default="text", required=True)

    # _compute_display_name (not name_get): name_get is ignored from Odoo 17
    # onwards, which left column pickers showing the technical slug instead of the
    # human label. _compute_display_name is the compute for display_name on every
    # supported version (16-19), so this works across the whole matrix.
    @api.depends("label", "name")
    def _compute_display_name(self):
        for col in self:
            col.display_name = col.label or col.name
