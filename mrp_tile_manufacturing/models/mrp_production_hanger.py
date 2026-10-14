# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpProductionHanger(models.Model):
    _name = 'mrp.production.hanger'
    _description = 'Production Hall / عنبر وصالة الإنتاج'
    _order = 'code, name'

    name = fields.Char(string='Hall Name / اسم الصالة', required=True, translate=True)
    code = fields.Char(string='Hall Code / كود الصالة')
    company_id = fields.Many2one('res.company', string='Company / الشركة', default=lambda self: self.env.company)
    warehouse_id = fields.Many2one('stock.warehouse', string='Plant / Factory / المصنع أو المستودع')
    workcenter_ids = fields.One2many('mrp.workcenter', 'hanger_id', string='Production Lines / خطوط الإنتاج')
    workcenter_count = fields.Integer(string='Lines Count', compute='_compute_workcenter_count')
    active = fields.Boolean(default=True)

    def _compute_workcenter_count(self):
        for rec in self:
            rec.workcenter_count = len(rec.workcenter_ids)
