# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    archive_department = fields.Selection([
        ('inventory', 'إدارة المخازن'),
        ('sale', 'إدارة المبيعات'),
        ('accounting', 'الإدارة المالية'),
    ], string='إدارة الأرشيف', index=True)

    archive_sub_app = fields.Selection([
        ('receipt', 'الاستلامات'),
        ('delivery', 'الصرف والتسليم'),
        ('adjustment', 'التسويات المخزنية'),
        ('agreement', 'الاتفاقيات'),
        ('sale_order', 'أوامر البيع'),
        ('vendor_bill', 'فواتير الموردين'),
        ('customer_invoice', 'فواتير العملاء'),
        ('vendor_refund', 'إشعارات موردين'),
        ('customer_refund', 'إشعارات عملاء'),
        ('payment_in', 'مقبوضات'),
        ('payment_out', 'مدفوعات سداد'),
        ('general_entry', 'قيود يومية'),
    ], string='التطبيق الفرعي للأرشيف', index=True)

    doc_type_id = fields.Many2one('archive.document.type', string='نوع الوثيقة والمستند', index=True)
    partner_id = fields.Many2one('res.partner', string='العميل / المورد', index=True)
    fiscal_year = fields.Char(string='السنة المالية', index=True)
    doc_reference = fields.Char(string='رقم المعاملة الأصلية', index=True)
    doc_date = fields.Date(string='تاريخ المعاملة', default=fields.Date.context_today, index=True)
    is_locked = fields.Boolean(
        string='مقفل رقابياً',
        default=False,
        help='يتم قفل المستند لمنع حذفه للحفاظ على المسار الرقابي وسجل التدقيق المالي والتشغيلي.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._fill_archive_metadata(vals)
        attachments = super().create(vals_list)
        return attachments

    def write(self, vals):
        # Prevent modifying is_locked unless manager
        if 'is_locked' in vals and not self.env.user.has_group('electronic_archive_management.group_archive_manager'):
            if not self.env.su:
                vals.pop('is_locked')
        return super().write(vals)

    def unlink(self):
        is_manager = self.env.user.has_group('electronic_archive_management.group_archive_manager')
        for rec in self:
            if rec.is_locked and not is_manager:
                raise UserError(_(
                    "غير مسموح بحذف المستند المؤرشف [%(name)s]!\n"
                    "المستند مقفل ومؤيد لمعاملة معتمدة داخل النظام لضمان النزاهة الرقابية وسجل التدقيق.\n"
                    "يرجى مراجعة مدير إدارة الأرشيف والرقابة."
                ) % {'name': rec.name})
        return super().unlink()

    def _fill_archive_metadata(self, vals):
        """Auto-populate metadata when attached to known business models"""
        res_model = vals.get('res_model')
        res_id = vals.get('res_id')
        if not res_model or not res_id:
            return

        try:
            record = self.env[res_model].browse(res_id)
            if not record.exists():
                return

            # Default date and fiscal year
            date_val = fields.Date.context_today(self)
            if hasattr(record, 'invoice_date') and record.invoice_date:
                date_val = record.invoice_date
            elif hasattr(record, 'date') and record.date:
                date_val = record.date
            elif hasattr(record, 'scheduled_date') and record.scheduled_date:
                date_val = fields.Date.to_date(record.scheduled_date)
            elif hasattr(record, 'date_order') and record.date_order:
                date_val = fields.Date.to_date(record.date_order)

            if not vals.get('doc_date'):
                vals['doc_date'] = date_val
            if not vals.get('fiscal_year') and date_val:
                vals['fiscal_year'] = str(date_val.year)

            # Partner
            if not vals.get('partner_id') and hasattr(record, 'partner_id') and record.partner_id:
                vals['partner_id'] = record.partner_id.id

            # Doc reference
            if not vals.get('doc_reference') and hasattr(record, 'name') and record.name:
                vals['doc_reference'] = record.name

            # Department & Sub-app mapping
            if res_model == 'stock.picking':
                vals['archive_department'] = 'inventory'
                picking_type = getattr(record, 'picking_type_code', False)
                if picking_type == 'incoming':
                    vals['archive_sub_app'] = 'receipt'
                elif picking_type == 'outgoing':
                    vals['archive_sub_app'] = 'delivery'
                else:
                    vals['archive_sub_app'] = 'delivery'
                if getattr(record, 'state', False) == 'done':
                    vals['is_locked'] = True

            elif res_model == 'account.move':
                vals['archive_department'] = 'accounting'
                move_type = getattr(record, 'move_type', 'entry')
                if move_type == 'in_invoice':
                    vals['archive_sub_app'] = 'vendor_bill'
                elif move_type == 'out_invoice':
                    vals['archive_sub_app'] = 'customer_invoice'
                elif move_type == 'in_refund':
                    vals['archive_sub_app'] = 'vendor_refund'
                elif move_type == 'out_refund':
                    vals['archive_sub_app'] = 'customer_refund'
                else:
                    vals['archive_sub_app'] = 'general_entry'
                if getattr(record, 'state', False) == 'posted':
                    vals['is_locked'] = True

            elif res_model == 'account.payment':
                vals['archive_department'] = 'accounting'
                payment_type = getattr(record, 'payment_type', 'inbound')
                vals['archive_sub_app'] = 'payment_out' if payment_type == 'outbound' else 'payment_in'
                if getattr(record, 'state', False) in ('posted', 'paid'):
                    vals['is_locked'] = True

            elif res_model == 'sale.order':
                vals['archive_department'] = 'sale'
                vals['archive_sub_app'] = 'sale_order'
                if getattr(record, 'state', False) in ('sale', 'done'):
                    vals['is_locked'] = True

        except Exception:
            pass
