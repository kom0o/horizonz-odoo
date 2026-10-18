# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class ArchiveDocumentType(models.Model):
    _name = 'archive.document.type'
    _description = 'Archive Document Type'
    _order = 'department, sequence, name'

    name = fields.Char(string='اسم نوع الوثيقة', required=True, translate=True)
    code = fields.Char(string='الرمز الكودي', index=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    department = fields.Selection([
        ('inventory', 'إدارة المخازن (Inventory)'),
        ('sale', 'إدارة المبيعات (Sales)'),
        ('accounting', 'الإدارة المالية (Accounting)'),
    ], string='الإدارة / التطبيق', required=True, default='inventory', index=True)
    
    sub_app = fields.Selection([
        ('receipt', 'الاستلامات (Receipts)'),
        ('delivery', 'الصرف والتسليم (Deliveries)'),
        ('adjustment', 'التسويات المخزنية (Adjustments)'),
        ('agreement', 'الاتفاقيات وعقود البيع (Agreements)'),
        ('sale_order', 'أوامر البيع (Sales Orders)'),
        ('vendor_bill', 'فواتير الموردين (Vendor Bills)'),
        ('customer_invoice', 'فواتير العملاء (Customer Invoices)'),
        ('vendor_refund', 'إشعارات مدين موردين (Vendor Credit Notes)'),
        ('customer_refund', 'إشعارات دائن عملاء (Customer Credit Notes)'),
        ('payment_in', 'مقبوضات العملاء (Customer Payments)'),
        ('payment_out', 'مدفوعات وسداد الموردين (Vendor Payments)'),
        ('general_entry', 'القيود اليومية للأستاذ العام (General Ledger Entries)'),
    ], string='التطبيق الفرعي', index=True)

    is_mandatory = fields.Boolean(string='إلزامي قبل الاعتماد', default=False,
                                  help='تحديد ما إذا كان رفع هذا المرفق شرطاً لازماً لترحيل أو إتمام المعاملة.')
    active = fields.Boolean(string='نشط', default=True)
    company_id = fields.Many2one('res.company', string='الشركة', default=lambda self: self.env.company)

    _sql_constraints = [
        ('code_company_uniq', 'unique (code, company_id)', 'كود نوع الوثيقة يجب أن يكون فريداً لكل شركة!')
    ]
