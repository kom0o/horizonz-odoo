# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ItAssetReturn(models.Model):
    _name = 'it.asset.return'
    _description = 'IT Asset Return & Clearance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'return_date desc, id desc'

    name = fields.Char(
        string='Return Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
        tracking=True
    )
    return_date = fields.Date(
        string='Return Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    return_from_id = fields.Many2one(
        'res.partner',
        string='Returning Employee',
        required=True,
        tracking=True,
        index=True
    )
    assignment_id = fields.Many2one(
        'it.asset.assign',
        string='Origin Custody Document',
        domain="[('assigned_to_id', '=', return_from_id)]",
        tracking=True
    )
    asset_ids = fields.Many2many(
        'it.asset',
        'it_asset_return_asset_rel',
        'return_id',
        'asset_id',
        string='Assets to Return',
        required=True,
        tracking=True
    )
    reason = fields.Selection([
        ('resignation', 'Resignation / Clearance (استقالة / إخلاء طرف)'),
        ('upgrade', 'Hardware Upgrade (ترقية / استبدال جهاز)'),
        ('damaged', 'Damaged / Needs Maintenance (عطل / صيانة)'),
        ('project_end', 'Project Completed (انتهاء مشروع)'),
        ('other', 'Other Reason (أسباب أخرى)'),
    ], string='Return Reason', default='resignation', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Returned & Verified'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Inspector Notes / Comments')

    # Related partner details for display & reports
    arabic_name = fields.Char(related='return_from_id.arabic_name', string='Arabic Name / الاسم بالعربي', readonly=True)
    national_id = fields.Char(related='return_from_id.national_id', string='National ID / رقم الهوية', readonly=True)
    employee_code = fields.Char(related='return_from_id.employee_code', string='Employee Code / الرقم الوظيفي', readonly=True)
    department_name = fields.Char(related='return_from_id.it_department_name', string='Department / الإدارة', readonly=True)
    report_manager_name = fields.Char(related='return_from_id.it_report_manager_name', string='Reporting Manager / المدير المباشر', readonly=True)
    phone = fields.Char(related='return_from_id.phone', string='Phone / Mobile', readonly=True)
    email = fields.Char(related='return_from_id.email', string='Email', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('it.asset.return.code') or _('New')
        return super(ItAssetReturn, self).create(vals_list)

    @api.onchange('return_from_id')
    def _onchange_return_from_id(self):
        if self.return_from_id:
            assigned_assets = self.env['it.asset'].search([('assigned_to_id', '=', self.return_from_id.id)])
            self.asset_ids = [(6, 0, assigned_assets.ids)]
            latest_assignment = self.env['it.asset.assign'].search([
                ('assigned_to_id', '=', self.return_from_id.id),
                ('state', '=', 'confirmed')
            ], order='id desc', limit=1)
            if latest_assignment:
                self.assignment_id = latest_assignment.id
        else:
            self.asset_ids = [(5, 0, 0)]
            self.assignment_id = False

    def action_confirm_return(self):
        """Processes asset return, resets stages to Stock, and clears active holder."""
        self.ensure_one()
        if not self.asset_ids:
            raise UserError(_("Please select at least one asset to return."))

        stock_stage = self.env['it.asset.stage'].search([('stage_type', '=', 'stock')], limit=1)
        reason_label = dict(self._fields['reason'].selection).get(self.reason, self.reason)

        for asset in self.asset_ids:
            asset.write({
                'stage_id': stock_stage.id if stock_stage else asset.stage_id.id,
                'returned': True,
                'return_date': self.return_date,
                'return_reason': reason_label,
                'returned_from_id': self.return_from_id.id,
                'previous_owner': self.return_from_id.name,
                'previous_issue_date': asset.assign_date,
                'assigned_to_id': False,
                'current_assignment_id': False,
            })
            asset.message_post(body=_(
                "Asset returned by %s on %s. Reason: %s."
            ) % (self.return_from_id.name, self.return_date, reason_label))

        self.write({'state': 'done'})
        self.message_post(body=_("Return process verified. %s asset(s) restored to Stock.") % len(self.asset_ids))

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_print_return_report(self):
        """Prints the bilingual IT Asset Return Form."""
        return self.env.ref('it_asset_management.action_report_it_asset_return').report_action(self)
