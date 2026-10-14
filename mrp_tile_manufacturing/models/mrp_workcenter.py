# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    line_code = fields.Integer(string='Line Number / رقم الخط', index=True)
    hanger_id = fields.Many2one('mrp.production.hanger', string='Production Hall / صالة الإنتاج', index=True)
    line_manufacturer = fields.Selection([
        ('ocem', 'OCEM (أوشم)'),
        ('masa', 'MASA (ماسا)'),
        ('herando', 'HERANDO (هيراندو)'),
        ('other', 'Other (أخرى)'),
    ], string='Manufacturer / الشركة المصنعة للماكينات', default='ocem')
    line_type = fields.Selection([
        ('terrazzo', 'Terrazzo & Marble Tiles (بلاط بلدي وكسر رخام)'),
        ('interlock', 'Interlock & Curbs (إنترلوك وبردورات)'),
        ('block', 'Concrete Blocks (بلك أسمنتي)'),
        ('cement', 'Cement Tiles (بلاط أسمنتي)'),
    ], string='Line Category / نوع الخط', default='terrazzo')
    tile_capacity_ids = fields.One2many('mrp.line.capacity', 'workcenter_id', string='Product Norms & Capacities / معايير الطاقات الإنتاجية')
    tile_capacity_count = fields.Integer(string='Configured Products', compute='_compute_tile_capacity_count')

    def _compute_tile_capacity_count(self):
        for rec in self:
            rec.tile_capacity_count = len(rec.tile_capacity_ids)
