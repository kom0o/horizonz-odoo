# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AccountMove(models.Model):
    _inherit = 'account.move'

    picking_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_picking_attachments',
        string='مرفقات حركات المخازن المرتبطة',
        help='يعرض تلقائياً وديناميكياً وبأثر رجعي كافة المرفقات (سندات التسليم الموقعة، صور الميزان، فواتير الموردين) المرفوعة على سندات المخازن المرتبطة بهذه الفاتورة.'
    )
    picking_attachment_count = fields.Integer(
        string='عدد مرفقات المخازن',
        compute='_compute_picking_attachments'
    )

    archive_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_archive_attachments',
        string='مرفقات القيد/الفاتورة المباشرة',
        help='جميع المستندات والمرفقات المرفوعة مباشرة على هذه الفاتورة/القيد.'
    )
    archive_attachment_count = fields.Integer(
        string='عدد المستندات المباشرة',
        compute='_compute_archive_attachments'
    )

    def _compute_archive_attachments(self):
        for move in self:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', move.id)
            ])
            move.archive_attachment_ids = attachments
            move.archive_attachment_count = len(attachments)

    def _compute_picking_attachments(self):
        for move in self:
            pickings = self.env['stock.picking']

            # 1. Customer Invoices: Link via Sales Orders
            if move.move_type in ('out_invoice', 'out_refund'):
                sale_orders = move.invoice_line_ids.sale_line_ids.order_id
                if not sale_orders and move.invoice_origin:
                    sale_orders = self.env['sale.order'].search([('name', '=', move.invoice_origin)])
                if sale_orders:
                    pickings |= sale_orders.picking_ids

            # 2. Vendor Bills: Link via Purchase Orders
            elif move.move_type in ('in_invoice', 'in_refund'):
                has_purchase = 'purchase.order' in self.env
                purchase_orders = self.env['purchase.order'] if has_purchase else False
                if has_purchase and 'purchase_line_ids' in move.invoice_line_ids._fields:
                    purchase_orders = move.invoice_line_ids.purchase_line_ids.order_id
                if not purchase_orders and move.invoice_origin and has_purchase:
                    purchase_orders = self.env['purchase.order'].search([('name', '=', move.invoice_origin)])
                if purchase_orders:
                    pickings |= purchase_orders.picking_ids

            # 3. Direct origin or name matching
            if move.name:
                pickings |= self.env['stock.picking'].search([('origin', '=', move.name)])
            if move.ref:
                pickings |= self.env['stock.picking'].search([('origin', '=', move.ref)])

            if pickings:
                attachments = self.env['ir.attachment'].search([
                    ('res_model', '=', 'stock.picking'),
                    ('res_id', 'in', pickings.ids)
                ])
                move.picking_attachment_ids = attachments
                move.picking_attachment_count = len(attachments)
            else:
                move.picking_attachment_ids = False
                move.picking_attachment_count = 0

    def action_post(self):
        res = super().action_post()
        for move in self:
            direct_attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', move.id)
            ])
            direct_attachments.sudo().write({'is_locked': True})
        return res

    def action_view_picking_attachments(self):
        self.ensure_one()
        return {
            'name': _('مرفقات المخازن المرتبطة بالفاتورة: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.picking_attachment_ids.ids)],
        }
