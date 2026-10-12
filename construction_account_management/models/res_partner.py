# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_construction_client = fields.Boolean(
        string='Is Construction Client / Contractor',
        help='Check if this contact is a construction employer, client, or subcontractor.'
    )
    partner_construction_type = fields.Selection([
        ('client', 'Developer / Employer'),
        ('contractor', 'Main Contractor'),
        ('subcontractor', 'Subcontractor'),
    ], string='Construction Relationship', default='client')

    construction_cr_number = fields.Char(string='CR / Contractor License No')
    credit_limit_amount = fields.Monetary(
        string='Credit Limit',
        currency_field='currency_id',
        help='Maximum receivable threshold approved for this client.'
    )

    construction_project_ids = fields.One2many(
        'construction.project',
        'partner_id',
        string='Construction Projects'
    )
    construction_project_count = fields.Integer(
        string='Project Count',
        compute='_compute_construction_financials'
    )

    total_construction_invoiced = fields.Monetary(
        string='Construction Invoiced',
        compute='_compute_construction_financials',
        currency_field='currency_id'
    )
    total_construction_paid = fields.Monetary(
        string='Construction Paid',
        compute='_compute_construction_financials',
        currency_field='currency_id'
    )
    total_construction_due = fields.Monetary(
        string='Construction Due Amount',
        compute='_compute_construction_financials',
        currency_field='currency_id'
    )
    total_retention_held = fields.Monetary(
        string='Total Retention Held',
        compute='_compute_construction_financials',
        currency_field='currency_id'
    )

    def _compute_construction_financials(self):
        for partner in self:
            projects = partner.construction_project_ids
            partner.construction_project_count = len(projects)

            invoices = self.env['account.move'].search([
                ('partner_id', 'child_of', partner.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                '|',
                ('is_construction_bill', '=', True),
                ('construction_project_id', 'in', projects.ids)
            ]) if projects or partner.is_construction_client else self.env['account.move']

            inv_total = sum(invoices.mapped('amount_total'))
            due_total = sum(invoices.mapped('amount_residual'))
            ret_total = sum(invoices.mapped('retention_amount'))

            partner.total_construction_invoiced = inv_total
            partner.total_construction_due = due_total
            partner.total_construction_paid = inv_total - due_total
            partner.total_retention_held = ret_total

    def action_view_construction_projects(self):
        self.ensure_one()
        return {
            'name': _('Construction Projects - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'construction.project',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_construction_invoices(self):
        self.ensure_one()
        return {
            'name': _('Construction Invoices - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', 'child_of', self.id),
                ('move_type', '=', 'out_invoice'),
                '|',
                ('is_construction_bill', '=', True),
                ('construction_project_id', 'in', self.construction_project_ids.ids)
            ],
            'context': {
                'default_move_type': 'out_invoice',
                'default_partner_id': self.id,
                'default_is_construction_bill': True,
            },
        }

    def action_view_construction_due(self):
        self.ensure_one()
        return {
            'name': _('Outstanding Due - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', 'child_of', self.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('amount_residual', '>', 0),
                '|',
                ('is_construction_bill', '=', True),
                ('construction_project_id', 'in', self.construction_project_ids.ids)
            ],
            'context': {
                'default_move_type': 'out_invoice',
                'default_partner_id': self.id,
                'default_is_construction_bill': True,
            },
        }
