# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class FinancialAssignee(models.Model):
    _name = 'financial.analyst.assignee'
    _description = 'Financial Domain Specialist / Assignee'
    _order = 'name'

    name = fields.Char(string='الاسم', required=True)
    user_id = fields.Many2one('res.users', string='مستخدم أودو', help='ربط بحساب المستخدم في النظام إن وجد')
    partner_id = fields.Many2one('res.partner', string='جهة الاتصال')
    email = fields.Char(string='البريد الإلكتروني', required=True)
    title = fields.Char(string='المسمى الوظيفي')
    department = fields.Char(string='الإدارة / القسم')
    company_ids = fields.Many2many('res.company', string='الشركات المفوّض بها')
    groups_str = fields.Char(string='رموز مجالات الاختصاص', default='prof, price, exp, grow, liq, lev, solv, eff, spares, ic, cf')
    odoo_alias = fields.Char(string='Odoo Helpdesk Alias', help='بريد تذاكر الدعم الفني في Odoo لإرسال التذاكر تلقائياً')
    active = fields.Boolean(string='نشط', default=True)

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id:
            self.name = self.user_id.name
            self.email = self.user_id.email
            self.partner_id = self.user_id.partner_id.id
            if self.user_id.company_ids:
                self.company_ids = [(6, 0, self.user_id.company_ids.ids)]
