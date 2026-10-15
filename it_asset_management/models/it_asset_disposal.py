# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ItAssetDisposal(models.Model):
    _name = 'it.asset.disposal'
    _description = 'IT Asset Disposal & Scrapping'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'disposal_date desc, id desc'

    name = fields.Char(
        string='Disposal Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
        tracking=True
    )
    asset_id = fields.Many2one(
        'it.asset',
        string='Asset to Dispose',
        required=True,
        tracking=True,
        domain="[('stage_type', 'in', ['stock', 'assigned'])]"
    )
    disposal_date = fields.Date(
        string='Disposal Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    buyer_id = fields.Many2one(
        'res.partner',
        string='Buyer / Scrap Merchant',
        tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    sell_price = fields.Monetary(
        string='Disposal Price (SAR)',
        currency_field='currency_id',
        default=0.0,
        tracking=True,
        help='Set to 0 for Scrap/Loss, or enter the liquidation sale price.'
    )
    disposal_type = fields.Selection([
        ('scrap', 'Scrap / Loss / Written-off (تخريد واستبعاد)'),
        ('sold', 'Sold / Liquidated (بيع أصل)'),
    ], string='Disposition Type', compute='_compute_disposal_type', store=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed & Decommissioned'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Disposal Reason / Notes (e.g., Stolen, Damaged, Liquidated)')

    # Asset overview
    asset_type = fields.Selection(related='asset_id.asset_type', string='Asset Type', readonly=True)
    serial_no = fields.Char(related='asset_id.serial_no', string='Serial Number', readonly=True)
    model_sku = fields.Char(related='asset_id.model_sku', string='Model & SKU', readonly=True)
    acquisition_date = fields.Date(related='asset_id.acquisition_date', string='Original Acquisition Date', readonly=True)
    acquisition_price = fields.Monetary(related='asset_id.acquisition_price', string='Original Acquisition Price', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('it.asset.disposal.code') or _('New')
        return super(ItAssetDisposal, self).create(vals_list)

    @api.depends('sell_price')
    def _compute_disposal_type(self):
        for rec in self:
            rec.disposal_type = 'sold' if rec.sell_price > 0 else 'scrap'

    def action_confirm_disposal(self):
        """Applies price-aware stage transition: 0 price -> Scrap, >0 price -> Sold."""
        self.ensure_one()
        if not self.asset_id:
            raise UserError(_("Please choose an asset to dispose."))

        if self.sell_price == 0:
            target_stage = self.env['it.asset.stage'].search([('stage_type', '=', 'scrap')], limit=1)
            action_desc = "Scrap"
        else:
            target_stage = self.env['it.asset.stage'].search([('stage_type', '=', 'sold')], limit=1)
            action_desc = f"Sold ({self.sell_price} {self.currency_id.symbol or ''})"

        self.asset_id.write({
            'stage_id': target_stage.id if target_stage else self.asset_id.stage_id.id,
            'disposal_date': self.disposal_date,
            'disposal_price': self.sell_price,
            'sold_to_id': self.buyer_id.id if self.buyer_id else False,
            'disposal_notes': self.notes,
            'assigned_to_id': False,
            'current_assignment_id': False,
        })

        self.asset_id.message_post(body=_(
            "Asset decommissioned via %s. Disposition: %s. Notes: %s"
        ) % (self.name, action_desc, self.notes or 'None'))

        self.write({'state': 'confirmed'})
        self.message_post(body=_("Disposal confirmed. Asset transitioned to %s.") % action_desc)

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
