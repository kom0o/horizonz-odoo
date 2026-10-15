# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    arabic_name = fields.Char(string='Arabic Name / الاسم بالعربي')
    national_id = fields.Char(string='National ID / رقم الهوية')
    employee_code = fields.Char(string='Employee Code / الرقم الوظيفي', index=True)
    it_department_name = fields.Char(string='Department / الإدارة')
    it_report_manager_name = fields.Char(string='Reporting Manager / المدير المباشر')
    it_company_name = fields.Char(string='Company Name / الشركة')

    assigned_asset_ids = fields.One2many(
        'it.asset', 'assigned_to_id', string='Assigned Assets'
    )
    assigned_asset_count = fields.Integer(
        string='Assigned Assets Count', compute='_compute_assigned_asset_count'
    )

    @api.depends('assigned_asset_ids')
    def _compute_assigned_asset_count(self):
        for partner in self:
            partner.assigned_asset_count = len(partner.assigned_asset_ids)

    def action_view_assigned_assets(self):
        self.ensure_one()
        return {
            'name': 'Assigned IT Assets',
            'type': 'ir.actions.act_window',
            'res_model': 'it.asset',
            'view_mode': 'list,kanban,form',
            'domain': [('assigned_to_id', '=', self.id)],
            'context': {'default_assigned_to_id': self.id},
        }
