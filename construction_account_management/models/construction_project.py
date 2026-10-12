# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class ConstructionProject(models.Model):
    _name = 'construction.project'
    _description = 'Construction Project / Site'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Project Name', required=True, tracking=True)
    code = fields.Char(string='Project Code', default=lambda self: _('New'), copy=False, readonly=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer / Client',
        required=True,
        tracking=True,
        help='Client or employer contracting this construction project.'
    )
    contract_value = fields.Monetary(
        string='Contract Value',
        currency_field='currency_id',
        required=True,
        tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id.id,
        required=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company.id,
        required=True
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Cost Center',
        help='Analytic account used to distribute revenues and costs for this construction site.'
    )
    retention_percentage = fields.Float(
        string='Default Retention (%)',
        default=5.0,
        help='Default percentage withheld from progress billings as warranty retention.'
    )
    date_start = fields.Date(string='Start Date', default=fields.Date.context_today)
    date_end = fields.Date(string='Expected Completion Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'Under Construction'),
        ('snagging', 'Handover & Snagging'),
        ('done', 'Completed & Closed'),
        ('cancel', 'Cancelled'),
    ], default='draft', string='Status', tracking=True)
    notes = fields.Html(string='Contract Scope & Terms')

    invoice_ids = fields.One2many(
        'account.move',
        'construction_project_id',
        string='Invoices & Claims'
    )
    payment_ids = fields.One2many(
        'account.payment',
        'construction_project_id',
        string='Payments & Receipts'
    )

    total_invoiced = fields.Monetary(
        string='Total Invoiced',
        compute='_compute_financials',
        store=True,
        currency_field='currency_id'
    )
    total_paid = fields.Monetary(
        string='Total Collected',
        compute='_compute_financials',
        store=True,
        currency_field='currency_id'
    )
    total_due = fields.Monetary(
        string='Outstanding Due',
        compute='_compute_financials',
        store=True,
        currency_field='currency_id'
    )
    total_retention_withheld = fields.Monetary(
        string='Retention Held',
        compute='_compute_financials',
        store=True,
        currency_field='currency_id'
    )

    invoice_count = fields.Integer(string='Invoices Count', compute='_compute_counts')
    payment_count = fields.Integer(string='Payments Count', compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('construction.project') or _('New')
        return super().create(vals_list)

    @api.depends('invoice_ids.state', 'invoice_ids.amount_total', 'invoice_ids.amount_residual', 'invoice_ids.retention_amount')
    def _compute_financials(self):
        for project in self:
            posted_invoices = project.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
            )
            total_inv = sum(posted_invoices.mapped('amount_total'))
            total_due = sum(posted_invoices.mapped('amount_residual'))
            total_ret = sum(posted_invoices.mapped('retention_amount'))
            project.total_invoiced = total_inv
            project.total_due = total_due
            project.total_paid = total_inv - total_due
            project.total_retention_withheld = total_ret

    def _compute_counts(self):
        for project in self:
            project.invoice_count = len(project.invoice_ids)
            project.payment_count = len(project.payment_ids)

    def action_in_progress(self):
        self.write({'state': 'in_progress'})

    def action_snagging(self):
        self.write({'state': 'snagging'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'name': _('Invoices & Claims - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('construction_project_id', '=', self.id)],
            'context': {
                'default_move_type': 'out_invoice',
                'default_partner_id': self.partner_id.id,
                'default_construction_project_id': self.id,
                'default_is_construction_bill': True,
                'default_retention_pct': self.retention_percentage,
            },
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            'name': _('Payments & Receipts - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('construction_project_id', '=', self.id)],
            'context': {
                'default_partner_type': 'customer',
                'default_partner_id': self.partner_id.id,
                'default_construction_project_id': self.id,
            },
        }
