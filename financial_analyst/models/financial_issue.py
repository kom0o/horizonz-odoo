# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class FinancialIssue(models.Model):
    _name = 'financial.analyst.issue'
    _description = 'Financial Indicator Issue and Improvement Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, due_date asc, id desc'

    name = fields.Char(string='رقم الإحالة', required=True, copy=False, readonly=True, default=lambda self: _('جديدة'))
    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env.company)
    period_id = fields.Many2one('financial.analyst.period', string='الفترة المالية', required=True, ondelete='cascade', tracking=True)
    
    kpi_code = fields.Char(string='رمز المؤشر', required=True, tracking=True)
    kpi_name = fields.Char(string='المؤشر', required=True, tracking=True)
    group_code = fields.Char(string='المجموعة')
    unit = fields.Char(string='الوحدة', default='%')
    direction = fields.Selection([('up', 'الأعلى أفضل'), ('down', 'الأقل أفضل')], string='الاتجاه', default='up')

    current_value = fields.Float(string='القيمة الحالية', digits=(16, 2), tracking=True)
    target_value = fields.Float(string='المستهدف', digits=(16, 2), tracking=True)
    new_target = fields.Float(string='المستهدف بعد التحسين', digits=(16, 2), tracking=True)

    cause = fields.Char(string='سبب المشكلة', required=True, tracking=True)
    cause_other = fields.Char(string='توضيح السبب')
    is_recurred = fields.Boolean(string='هل تكررت المشكلة؟', default=False)
    recur_count = fields.Integer(string='عدد مرات التكرار', default=0)
    recur_details = fields.Text(string='تفاصيل التكرار')

    assignee_id = fields.Many2one('financial.analyst.assignee', string='صاحب الاختصاص', required=True, tracking=True)
    assignee_email = fields.Char(related='assignee_id.email', string='بريد صاحب الاختصاص')
    user_id = fields.Many2one('res.users', string='متابع الإحالة في أودو', tracking=True)

    priority = fields.Selection([
        ('low', 'منخفضة'),
        ('med', 'متوسطة'),
        ('high', 'عالية'),
        ('urgent', 'عاجلة جدًا'),
    ], string='الأولوية', default='high', required=True, tracking=True)

    due_date = fields.Date(string='تاريخ الاستحقاق', required=True, tracking=True)
    plan = fields.Text(string='خطة التحسين التنفيذية', required=True, tracking=True)

    status = fields.Selection([
        ('open', 'مفتوحة'),
        ('in_progress', 'قيد التنفيذ'),
        ('closed', 'مغلقة'),
        ('reopened', 'معاد فتحها'),
    ], string='الحالة', default='open', required=True, tracking=True)

    closed_by_id = fields.Many2one('res.users', string='أغلقها', tracking=True)
    closed_at = fields.Datetime(string='تاريخ الإغلاق', tracking=True)
    reopen_count = fields.Integer(string='مرات إعادة الفتح', default=0)
    reopen_reason = fields.Text(string='سبب إعادة الفتح', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('جديدة')) == _('جديدة'):
                vals['name'] = self.env['ir.sequence'].next_by_code('financial.analyst.issue') or _('ISS-%s') % fields.Date.today().strftime('%Y%m%d')
        return super().create(vals_list)

    def action_close(self):
        self.write({
            'status': 'closed',
            'closed_by_id': self.env.user.id,
            'closed_at': fields.Datetime.now()
        })
        self.message_post(body=_("تم إغلاق الإحالة بنجاح بواسطة %s") % self.env.user.name)

    def action_reopen(self, reason=''):
        self.write({
            'status': 'reopened',
            'reopen_count': self.reopen_count + 1,
            'reopen_reason': reason,
        })
        self.message_post(body=_("تمت إعادة فتح الإحالة. السبب: %s") % reason)
