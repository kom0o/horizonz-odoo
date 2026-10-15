# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ItAssetAssign(models.Model):
    _name = 'it.asset.assign'
    _description = 'IT Asset Custody Assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'assign_date desc, id desc'

    name = fields.Char(
        string='Assignment Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
        tracking=True
    )
    assigned_to_id = fields.Many2one(
        'res.partner',
        string='Employee / Custodian',
        required=True,
        tracking=True,
        index=True
    )
    assign_date = fields.Date(
        string='Assignment Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Waiting Employee Confirmation'),
        ('confirmed', 'Confirmed / In Custody'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    # Equipment Bundle breakdown
    main_asset_id = fields.Many2one(
        'it.asset',
        string='Main Computer (Laptop/PC/Tablet)',
        domain="[('asset_type', 'in', ['laptop', 'pc', 'tablet', 'all_in_one'])]",
        tracking=True
    )
    monitor_asset_id = fields.Many2one(
        'it.asset',
        string='Monitor / Screen',
        domain="[('asset_type', '=', 'screen')]",
        tracking=True
    )
    keyboard_asset_id = fields.Many2one(
        'it.asset',
        string='Keyboard',
        domain="[('asset_type', '=', 'keyboard')]",
        tracking=True
    )
    mouse_asset_id = fields.Many2one(
        'it.asset',
        string='Mouse',
        domain="[('asset_type', '=', 'mouse')]",
        tracking=True
    )
    printer_asset_id = fields.Many2one(
        'it.asset',
        string='Printer',
        domain="[('asset_type', '=', 'printer')]",
        tracking=True
    )

    # Multi-asset relation (All equipment in this assignment)
    asset_ids = fields.Many2many(
        'it.asset',
        'it_asset_assign_asset_rel',
        'assign_id',
        'asset_id',
        string='All Assigned Assets',
        tracking=True
    )

    # Related partner details for display & reports
    arabic_name = fields.Char(related='assigned_to_id.arabic_name', string='Arabic Name / الاسم بالعربي', readonly=True)
    national_id = fields.Char(related='assigned_to_id.national_id', string='National ID / رقم الهوية', readonly=True)
    employee_code = fields.Char(related='assigned_to_id.employee_code', string='Employee Code / الرقم الوظيفي', readonly=True)
    department_name = fields.Char(related='assigned_to_id.it_department_name', string='Department / الإدارة', readonly=True)
    report_manager_name = fields.Char(related='assigned_to_id.it_report_manager_name', string='Reporting Manager / المدير المباشر', readonly=True)
    phone = fields.Char(related='assigned_to_id.phone', string='Phone / Mobile', readonly=True)
    email = fields.Char(related='assigned_to_id.email', string='Email', readonly=True)

    # WhatsApp & n8n Integration
    whatsapp_status = fields.Selection([
        ('pending', 'Not Sent'),
        ('sent', 'Sent to WhatsApp'),
        ('approved', 'Approved Digitally'),
        ('failed', 'Webhook Failed'),
    ], string='WhatsApp Confirmation', default='pending', tracking=True)
    whatsapp_sent_date = fields.Datetime(string='Webhook Sent Date', readonly=True)

    notes = fields.Text(string='Internal Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('it.asset.assign.code') or _('New')
        records = super(ItAssetAssign, self).create(vals_list)
        for rec in records:
            rec._sync_bundled_assets()
        return records

    def write(self, vals):
        res = super(ItAssetAssign, self).write(vals)
        if any(f in vals for f in ['main_asset_id', 'monitor_asset_id', 'keyboard_asset_id', 'mouse_asset_id', 'printer_asset_id']):
            for rec in self:
                rec._sync_bundled_assets()
        return res

    def _sync_bundled_assets(self):
        """Sync bundled equipment fields into asset_ids."""
        for rec in self:
            bundled = (
                rec.main_asset_id |
                rec.monitor_asset_id |
                rec.keyboard_asset_id |
                rec.mouse_asset_id |
                rec.printer_asset_id
            )
            # Combine bundled with any manually selected asset_ids
            current_assets = rec.asset_ids | bundled
            rec.asset_ids = [(6, 0, current_assets.ids)]

    def action_send_whatsapp_approval(self):
        """Sends webhook notification to n8n to initiate WhatsApp custody approval."""
        self.ensure_one()
        if not self.asset_ids:
            raise UserError(_("Please add at least one asset to assign before sending for confirmation."))

        webhook_url = self.env['ir.config_parameter'].sudo().get_param(
            'it_asset.n8n_webhook_url',
            default='https://n8n.srv1247626.hstgr.cloud/webhook/96e11f25-dc57-4043-b8af-0a502b8118e6'
        )

        assets_payload = []
        for asset in self.asset_ids:
            assets_payload.append({
                'id': asset.id,
                'ref': asset.ref,
                'name': asset.name,
                'type': asset.asset_type,
                'serial_no': asset.serial_no or '',
                'model_sku': asset.model_sku or '',
                'cpu': asset.cpu or '',
                'ram': asset.ram or '',
            })

        payload = {
            'record_id': self.id,
            'assignment_ref': self.name,
            'assign_date': str(self.assign_date),
            'employee': {
                'id': self.assigned_to_id.id,
                'name': self.assigned_to_id.name,
                'arabic_name': self.arabic_name or '',
                'employee_code': self.employee_code or '',
                'national_id': self.national_id or '',
                'phone': self.phone or '',
                'email': self.email or '',
                'department': self.department_name or '',
            },
            'assets': assets_payload,
        }

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            if response.status_code in [200, 201]:
                self.write({
                    'state': 'waiting_approval',
                    'whatsapp_status': 'sent',
                    'whatsapp_sent_date': fields.Datetime.now(),
                })
                self.message_post(body=_(
                    "WhatsApp approval request successfully sent to employee via n8n webhook (%s)."
                ) % self.phone)
            else:
                self.write({'whatsapp_status': 'failed'})
                self.message_post(body=_(
                    "Webhook notification failed with status code %s: %s"
                ) % (response.status_code, response.text))
        except Exception as e:
            _logger.error("Error sending WhatsApp webhook to %s: %s", webhook_url, str(e))
            self.write({'whatsapp_status': 'failed'})
            self.message_post(body=_("Could not send WhatsApp webhook: %s") % str(e))

    def action_confirm(self):
        """Confirms the assignment, detaches transferred assets from previous holders, and sets stages to Assigned."""
        self.ensure_one()
        assigned_stage = self.env['it.asset.stage'].search([('stage_type', '=', 'assigned')], limit=1)
        if not assigned_stage:
            assigned_stage = self.env['it.asset.stage'].create({
                'name': 'Assigned',
                'stage_type': 'assigned',
                'sequence': 20,
            })

        for asset in self.asset_ids:
            # 1. Reset returned status
            if asset.returned:
                asset.returned = False

            # 2. Transfer logic: Check if assigned to another person previously
            previous_assignments = self.env['it.asset.assign'].search([
                ('asset_ids', 'in', asset.id),
                ('id', '!=', self.id),
                ('state', '=', 'confirmed'),
            ])
            for prev in previous_assignments:
                # Remove asset from old assignment
                prev.asset_ids = [(3, asset.id)]
                prev.message_post(body=_(
                    "Asset %s was transferred to new assignment %s (%s)."
                ) % (asset.name, self.name, self.assigned_to_id.name))

            # 3. Update asset record
            asset_vals = {
                'stage_id': assigned_stage.id,
                'assigned_to_id': self.assigned_to_id.id,
                'assign_date': self.assign_date,
                'current_assignment_id': self.id,
                'previous_owner': asset.assigned_to_id.name if asset.assigned_to_id else False,
                'has_been_assigned': True,
            }
            if asset.condition == 'new':
                asset_vals['condition'] = 'used'
            asset.write(asset_vals)

        self.write({
            'state': 'confirmed',
            'whatsapp_status': 'approved' if self.whatsapp_status == 'sent' else self.whatsapp_status,
        })
        self.message_post(body=_("Custody Assignment Confirmed. %s asset(s) marked as Assigned.") % len(self.asset_ids))

    def action_set_draft(self):
        """Resets assignment back to draft and returns assets to Stock stage."""
        self.ensure_one()
        stock_stage = self.env['it.asset.stage'].search([('stage_type', '=', 'stock')], limit=1)
        for asset in self.asset_ids:
            vals = {
                'assigned_to_id': False,
                'current_assignment_id': False,
            }
            if stock_stage:
                vals['stage_id'] = stock_stage.id
            asset.write(vals)

        self.write({'state': 'draft', 'whatsapp_status': 'pending'})
        self.message_post(body=_("Assignment reverted to Draft. Assets set back to Stock."))

    def action_cancel(self):
        """Cancels assignment and releases any locked assets."""
        self.action_set_draft()
        self.write({'state': 'cancelled'})

    def action_print_issue_report(self):
        """Prints the bilingual IT Asset Issue / Custody Form."""
        return self.env.ref('it_asset_management.action_report_it_asset_issue').report_action(self)
