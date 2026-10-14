# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class FinancialSalesLine(models.Model):
    _name = 'financial.analyst.sales.line'
    _description = 'Financial Analyst Sales Breakdown Line'
    _order = 'value desc'

    period_id = fields.Many2one('financial.analyst.period', string='الفترة', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='period_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string='المنتج')
    code = fields.Char(string='كود الصنف')
    item = fields.Char(string='اسم الصنف', required=True)
    terms = fields.Char(string='شروط التسليم', default='ex')
    item_type = fields.Char(string='التصنيف')
    unit = fields.Char(string='الوحدة')
    qty = fields.Float(string='الكمية', digits=(16, 2))
    price = fields.Float(string='متوسط السعر', digits=(16, 4))
    value = fields.Float(string='القيمة الإجمالية', digits=(16, 2))


class FinancialMaterialLine(models.Model):
    _name = 'financial.analyst.material.line'
    _description = 'Financial Analyst Raw Materials Line'
    _order = 'value desc'

    period_id = fields.Many2one('financial.analyst.period', string='الفترة', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='period_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string='المادة')
    code = fields.Char(string='كود المادة')
    item = fields.Char(string='اسم المادة الخام', required=True)
    unit = fields.Char(string='الوحدة')
    qty = fields.Float(string='الكمية المشتراة', digits=(16, 2))
    used = fields.Float(string='الكمية المستخدمة', digits=(16, 2))
    value = fields.Float(string='القيمة', digits=(16, 2))


class FinancialRepLine(models.Model):
    _name = 'financial.analyst.rep.line'
    _description = 'Financial Analyst Sales Rep Line'
    _order = 'value desc'

    period_id = fields.Many2one('financial.analyst.period', string='الفترة', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='period_id.company_id', store=True)
    user_id = fields.Many2one('res.users', string='المندوب في أودو')
    rep = fields.Char(string='اسم المندوب', required=True)
    qty = fields.Float(string='الكمية الإجمالية', digits=(16, 2))
    value = fields.Float(string='قيمة المبيعات', digits=(16, 2))
    invoices = fields.Integer(string='عدد الفواتير')
    customers = fields.Integer(string='عدد العملاء')


class FinancialIntercompanyLine(models.Model):
    _name = 'financial.analyst.intercompany.line'
    _description = 'Financial Analyst Intercompany Line'

    period_id = fields.Many2one('financial.analyst.period', string='الفترة', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='period_id.company_id', store=True)
    partner_id = fields.Many2one('res.partner', string='الشركة الشقيقة')
    name = fields.Char(string='اسم الشركة الشقيقة', required=True)
    rec_trade = fields.Float(string='مدين تجاري', digits=(16, 2))
    rec_non_trade = fields.Float(string='مدين بالإنابة (غير تجاري)', digits=(16, 2))
    pay_trade = fields.Float(string='دائن تجاري', digits=(16, 2))
    pay_non_trade = fields.Float(string='دائن بالإنابة (غير تجاري)', digits=(16, 2))
    net_balance = fields.Float(string='صافي الرصيد', compute='_compute_net', store=True, digits=(16, 2))

    @api.depends('rec_trade', 'rec_non_trade', 'pay_trade', 'pay_non_trade')
    def _compute_net(self):
        for line in self:
            line.net_balance = (line.rec_trade + line.rec_non_trade) - (line.pay_trade + line.pay_non_trade)
