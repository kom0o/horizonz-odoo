# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpTileGroup(models.Model):
    _name = 'mrp.tile.group'
    _description = 'Tile Product Group / مجموعة أصناف البلاط والأسمنتي'
    _order = 'code, name'

    name = fields.Char(string='Group Name / اسم المجموعة', required=True, translate=True)
    code = fields.Integer(string='Code / الكود', index=True)
    product_category_id = fields.Many2one('product.category', string='Inventory Category / فئة المخزون')
    description = fields.Text(string='Description / الوصف')
    active = fields.Boolean(default=True)
    product_count = fields.Integer(string='Products Count', compute='_compute_product_count')

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = self.env['product.template'].search_count([('tile_group_id', '=', rec.id)])
