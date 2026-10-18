# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class ArchiveDocumentSearch(models.TransientModel):
    _name = 'archive.document.search'
    _description = 'محرك البحث والاسترجاع المركزي بالأرشيف الإلكتروني'

    # Level 1: Company
    company_id = fields.Many2one(
        'res.company',
        string='1. الشركة (Company)',
        default=lambda self: self.env.company,
        required=True
    )

    # Level 2: Fiscal Year
    fiscal_year = fields.Selection([
        ('2023', '2023'),
        ('2024', '2024'),
        ('2025', '2025'),
        ('2026', '2026'),
        ('2027', '2027'),
    ], string='2. السنة المالية (Fiscal Year)', default='2026')

    # Level 3: Department / Application
    department = fields.Selection([
        ('all', 'جميع التطبيقات (All Applications)'),
        ('inventory', 'إدارة المخازن (Inventory)'),
        ('sale', 'إدارة المبيعات (Sales)'),
        ('accounting', 'الإدارة المالية (Accounting)'),
    ], string='3. التطبيق (Application)', default='all', required=True)

    # Level 4: Sub Application
    sub_app = fields.Selection([
        ('all', 'الكل (All)'),
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
    ], string='4. التطبيق الفرعي (Sub-Application)', default='all')

    # Refined search criteria
    doc_number = fields.Char(string='رقم المستند (Document Number)', help='مثال: INV/2026/001, WH/IN/04518, S31479')
    date_from = fields.Date(string='من تاريخ (Date From)')
    date_to = fields.Date(string='إلى تاريخ (Date To)')
    doc_type_id = fields.Many2one('archive.document.type', string='نوع المستند (Document Type)')
    partner_id = fields.Many2one('res.partner', string='اسم العميل أو المورد (Customer / Vendor)')
    query_text = fields.Char(string='بحث شامل (Universal Search)', help='بحث في جميع الحقول والملاحظات وأسماء الملفات')

    # Search results
    result_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='نتائج البحث المسترجعة',
        readonly=True
    )
    result_count = fields.Integer(string='عدد النتائج', compute='_compute_result_count')

    @api.depends('result_attachment_ids')
    def _compute_result_count(self):
        for rec in self:
            rec.result_count = len(rec.result_attachment_ids)

    @api.onchange('department')
    def _onchange_department(self):
        if self.department == 'all':
            self.sub_app = 'all'
        elif self.department == 'inventory':
            self.sub_app = 'receipt'
        elif self.department == 'sale':
            self.sub_app = 'sale_order'
        elif self.department == 'accounting':
            self.sub_app = 'customer_invoice'

    def action_search(self):
        self.ensure_one()
        domain = []

        # Company filter
        if self.company_id:
            domain.append(('company_id', 'in', [False, self.company_id.id]))

        # Fiscal Year
        if self.fiscal_year:
            domain.append(('fiscal_year', '=', self.fiscal_year))

        # Department filter
        if self.department and self.department != 'all':
            domain.append(('archive_department', '=', self.department))

        # Sub-application filter
        if self.sub_app and self.sub_app != 'all':
            domain.append(('archive_sub_app', '=', self.sub_app))

        # Document Type
        if self.doc_type_id:
            domain.append(('doc_type_id', '=', self.doc_type_id.id))

        # Partner filter
        if self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))

        # Document number
        if self.doc_number:
            domain.append('|')
            domain.append(('doc_reference', 'ilike', self.doc_number.strip()))
            domain.append(('name', 'ilike', self.doc_number.strip()))

        # Date range
        if self.date_from:
            domain.append(('doc_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('doc_date', '<=', self.date_to))

        # Universal Query
        if self.query_text:
            text = self.query_text.strip()
            domain.append('|')
            domain.append('|')
            domain.append(('name', 'ilike', text))
            domain.append(('doc_reference', 'ilike', text))
            domain.append(('description', 'ilike', text))

        attachments = self.env['ir.attachment'].search(domain, order='create_date desc', limit=200)
        self.result_attachment_ids = [(6, 0, attachments.ids)]

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'archive.document.search',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'main',
        }

    def action_reset(self):
        self.ensure_one()
        self.write({
            'fiscal_year': '2026',
            'department': 'all',
            'sub_app': 'all',
            'doc_number': False,
            'date_from': False,
            'date_to': False,
            'doc_type_id': False,
            'partner_id': False,
            'query_text': False,
            'result_attachment_ids': [(5, 0, 0)]
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'archive.document.search',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'main',
        }
