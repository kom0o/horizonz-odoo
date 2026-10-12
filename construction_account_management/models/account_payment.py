# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    construction_project_id = fields.Many2one(
        'construction.project',
        string='Construction Project / Site',
        ondelete='set null',
        copy=False,
        help='Project site or contract this payment receipt is allocated towards.'
    )
    payment_nature = fields.Selection([
        ('standard', 'Normal Invoice Payment'),
        ('advance', 'Mobilization Advance'),
        ('retention_release', 'Retention Guarantee Release'),
    ], string='Payment Nature', default='standard')

    @api.onchange('construction_project_id')
    def _onchange_construction_project_id(self):
        if self.construction_project_id and not self.partner_id:
            self.partner_id = self.construction_project_id.partner_id
