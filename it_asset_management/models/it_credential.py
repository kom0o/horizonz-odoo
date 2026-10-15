# -*- coding: utf-8 -*-
from odoo import models, fields

class ItCredential(models.Model):
    _name = 'it.credential'
    _description = 'IT Credential & Password Vault'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='System / Account Description', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    url = fields.Char(string='Portal URL / Link')
    username = fields.Char(string='Username / Account', tracking=True)
    password = fields.Char(string='Password')
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes / Instructions')
