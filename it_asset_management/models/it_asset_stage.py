# -*- coding: utf-8 -*-
from odoo import models, fields

class ItAssetStage(models.Model):
    _name = 'it.asset.stage'
    _description = 'IT Asset Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    fold = fields.Boolean(
        string='Folded in Kanban',
        help='This stage will be folded by default in the kanban view.'
    )
    stage_type = fields.Selection([
        ('stock', 'In Stock'),
        ('assigned', 'Assigned'),
        ('scrap', 'Scrap'),
        ('sold', 'Sold'),
        ('other', 'Other'),
    ], string='System Type', default='stock', required=True,
       help='Defines automated lifecycle behaviors linked to this stage.')
    description = fields.Text(string='Description')
