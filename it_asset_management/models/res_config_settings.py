# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    it_asset_n8n_webhook_url = fields.Char(
        string='n8n WhatsApp Webhook URL',
        config_parameter='it_asset.n8n_webhook_url',
        default='https://n8n.srv1247626.hstgr.cloud/webhook/96e11f25-dc57-4043-b8af-0a502b8118e6',
        help='Outgoing webhook URL triggered to send custody confirmation requests via n8n/WhatsApp.'
    )
    it_asset_webhook_secret = fields.Char(
        string='Webhook Security Token',
        config_parameter='it_asset.webhook_secret',
        default='it_assets_secure_token',
        help='Secret token expected in incoming n8n approval webhook callbacks.'
    )
