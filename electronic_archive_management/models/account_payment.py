# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    archive_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_archive_attachments',
        string='المستندات المؤيدة للسداد/القبض',
        help='إشعارات التحويل البنكي، إيصالات السداد، والشيكات المرفقة بهذه العملية.'
    )
    archive_attachment_count = fields.Integer(
        string='عدد المستندات المرفقة',
        compute='_compute_archive_attachments'
    )

    def _compute_archive_attachments(self):
        for payment in self:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.payment'),
                ('res_id', '=', payment.id)
            ])
            payment.archive_attachment_ids = attachments
            payment.archive_attachment_count = len(attachments)

    def action_post(self):
        res = super().action_post()
        for payment in self:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.payment'),
                ('res_id', '=', payment.id)
            ])
            attachments.sudo().write({'is_locked': True})
        return res

    def action_view_archive_attachments(self):
        self.ensure_one()
        return {
            'name': _('مستندات السداد/القبض: %s') % (self.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'tree,form',
            'domain': [('res_model', '=', 'account.payment'), ('res_id', '=', self.id)],
            'context': {
                'default_res_model': 'account.payment',
                'default_res_id': self.id,
                'default_archive_department': 'accounting',
                'default_archive_sub_app': 'payment_out' if self.payment_type == 'outbound' else 'payment_in',
                'default_partner_id': self.partner_id.id if self.partner_id else False,
                'default_doc_reference': self.name,
            }
        }
