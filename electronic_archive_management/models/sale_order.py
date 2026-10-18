# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    archive_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_archive_attachments',
        string='مستندات البيع والاتفاقية',
        help='طلب الشراء من العميل، شروط الاتفاقية، والعروض المعتمدة المرفقة بأمر البيع.'
    )
    archive_attachment_count = fields.Integer(
        string='عدد المستندات',
        compute='_compute_archive_attachments'
    )

    def _compute_archive_attachments(self):
        for order in self:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'sale.order'),
                ('res_id', '=', order.id)
            ])
            order.archive_attachment_ids = attachments
            order.archive_attachment_count = len(attachments)

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'sale.order'),
                ('res_id', '=', order.id)
            ])
            attachments.sudo().write({'is_locked': True})
        return res

    def action_view_archive_attachments(self):
        self.ensure_one()
        return {
            'name': _('مستندات طلب الشراء والاتفاقية: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'tree,form',
            'domain': [('res_model', '=', 'sale.order'), ('res_id', '=', self.id)],
            'context': {
                'default_res_model': 'sale.order',
                'default_res_id': self.id,
                'default_archive_department': 'sale',
                'default_archive_sub_app': 'sale_order',
                'default_partner_id': self.partner_id.id if self.partner_id else False,
                'default_doc_reference': self.name,
            }
        }
