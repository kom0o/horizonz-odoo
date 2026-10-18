# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    archive_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_archive_attachments',
        string='المستندات المؤرشفة',
        help='جميع الوثائق والمستندات المؤرشفة الملحقة بسند المخزن الحالي.'
    )
    archive_attachment_count = fields.Integer(
        string='عدد المستندات المؤرشفة',
        compute='_compute_archive_attachments'
    )

    def _compute_archive_attachments(self):
        for picking in self:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'stock.picking'),
                ('res_id', '=', picking.id)
            ])
            picking.archive_attachment_ids = attachments
            picking.archive_attachment_count = len(attachments)

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.state == 'done':
                attachments = self.env['ir.attachment'].search([
                    ('res_model', '=', 'stock.picking'),
                    ('res_id', '=', picking.id)
                ])
                attachments.sudo().write({'is_locked': True})
        return res

    def action_view_archive_attachments(self):
        self.ensure_one()
        return {
            'name': _('المستندات المؤرشفة للسند: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'tree,form',
            'domain': [('res_model', '=', 'stock.picking'), ('res_id', '=', self.id)],
            'context': {
                'default_res_model': 'stock.picking',
                'default_res_id': self.id,
                'default_archive_department': 'inventory',
                'default_archive_sub_app': 'receipt' if self.picking_type_code == 'incoming' else 'delivery',
                'default_partner_id': self.partner_id.id if self.partner_id else False,
                'default_doc_reference': self.name,
            }
        }
