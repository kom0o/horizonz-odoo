# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    is_construction_bill = fields.Boolean(
        string='Is Construction Bill',
        copy=False,
        help='Indicates whether this invoice represents a construction contract milestone or progress claim.'
    )
    construction_project_id = fields.Many2one(
        'construction.project',
        string='Construction Project / Site',
        ondelete='set null',
        copy=False,
        help='Project site contract associated with this billing.'
    )
    billing_type = fields.Selection([
        ('advance', 'Mobilization Advance'),
        ('progress', 'Progress Milestone / WCC'),
        ('retention', 'Retention Release'),
        ('final', 'Final Claim'),
    ], string='Billing Type', default='progress')

    wcc_reference = fields.Char(
        string='Work Completion Certificate (WCC)',
        help='Consultant or engineer certificate reference number.'
    )
    work_completion_pct = fields.Float(
        string='Certified Work Done (%)',
        help='Cumulative or milestone percentage completed certified by the supervising engineer.'
    )
    retention_pct = fields.Float(
        string='Retention Rate (%)',
        help='Percentage withheld from this invoice as defect warranty retention.'
    )
    retention_amount = fields.Monetary(
        string='Retention Withheld',
        compute='_compute_retention_and_net',
        store=True,
        currency_field='currency_id'
    )
    net_claim_amount = fields.Monetary(
        string='Net Payable Claim',
        compute='_compute_retention_and_net',
        store=True,
        currency_field='currency_id'
    )
    days_overdue = fields.Integer(
        string='Days Overdue',
        compute='_compute_days_overdue'
    )

    @api.onchange('construction_project_id')
    def _onchange_construction_project_id(self):
        if self.construction_project_id:
            self.is_construction_bill = True
            if not self.partner_id:
                self.partner_id = self.construction_project_id.partner_id
            if not self.retention_pct and self.billing_type != 'retention':
                self.retention_pct = self.construction_project_id.retention_percentage

    @api.depends('amount_untaxed', 'retention_pct', 'amount_total', 'is_construction_bill', 'billing_type')
    def _compute_retention_and_net(self):
        for move in self:
            if move.is_construction_bill and move.billing_type != 'retention' and move.retention_pct > 0:
                ret_amt = (move.amount_untaxed * move.retention_pct) / 100.0
                move.retention_amount = ret_amt
                move.net_claim_amount = move.amount_total - ret_amt
            else:
                move.retention_amount = 0.0
                move.net_claim_amount = move.amount_total

    def _compute_days_overdue(self):
        today = fields.Date.context_today(self)
        for move in self:
            if (
                move.move_type == 'out_invoice'
                and move.state == 'posted'
                and move.payment_state in ('not_paid', 'partial')
                and move.invoice_date_due
                and move.invoice_date_due < today
            ):
                move.days_overdue = (today - move.invoice_date_due).days
            else:
                move.days_overdue = 0
