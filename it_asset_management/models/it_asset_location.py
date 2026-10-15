# -*- coding: utf-8 -*-
from odoo import models, fields

class ItAssetLocation(models.Model):
    _name = 'it.asset.location'
    _description = 'IT Asset Location'
    _order = 'name'

    name = fields.Char(string='Location Name', required=True, translate=True)
    code = fields.Char(string='Location Code')
    active = fields.Boolean(string='Active', default=True)
    address = fields.Char(string='Physical Address / Branch')
    notes = fields.Text(string='Notes')
