# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    financial_analyst_gemini_api_key = fields.Char(
        string='Google Gemini API Key',
        config_parameter='financial_analyst.gemini_api_key',
        help='مفتاح الربط مع Google Gemini لتفعيل المحلل المالي الذكي واقتراح خطط التحسين'
    )
    financial_analyst_gemini_model = fields.Char(
        string='Gemini Model',
        config_parameter='financial_analyst.gemini_model',
        default='gemini-2.5-flash',
        help='اسم النموذج المستخدم مثل gemini-2.5-flash أو gemini-1.5-pro'
    )
    financial_analyst_gemini_base_url = fields.Char(
        string='Gemini Base URL',
        config_parameter='financial_analyst.gemini_base_url',
        default='https://generativelanguage.googleapis.com',
    )
