# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_tile_product = fields.Boolean(string='Is Tile / Concrete Product / منتج بلاط أو خرساني', default=False)
    tile_size = fields.Char(string='Dimensions / المقاس', help='e.g. 20x20, 25x25, 30x30, 40x40')
    tile_color = fields.Char(string='Color / اللون', help='e.g. أبيض, رصاصي, أحمر, أسود')
    units_per_sqm = fields.Float(string='Units per SQM / عدد البلاطات في المتر المربع', digits=(12, 2))
    triala_capacity_sqm = fields.Float(string='Trailer Capacity (m²) / حمولة التريلا بالمتر المربع', digits=(12, 2))
    crane_capacity_sqm = fields.Float(string='Crane Capacity (m²) / حمولة الكرين بالمتر المربع', digits=(12, 2))
    tile_group_id = fields.Many2one('mrp.tile.group', string='Tile Group / مجموعة البلاط')
