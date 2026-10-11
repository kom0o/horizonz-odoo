# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Ahammed Harshad P(odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, exceptions, fields, models, _


class CommissionProduct(models.Model):
    """Commission.product model is defined here"""
    _name = 'commission.product'
    _description = 'Commission Product Wise'

    user_id = fields.Many2one('res.users', string='User',
                              help='Select the User')
    category_id = fields.Many2one('product.category',
                                  string='Product Category',
                                  help='Select the Product Category')
    category_ids = fields.Many2many('product.category',
                                    string='Product Category Reference',
                                    help="To set the domain for the "
                                         "category_id",
                                    compute="_onchange_category_id")
    product_id = fields.Many2one('product.product', string='Product',
                                 help='Select the product')
    target_type = fields.Selection([
        ('none', 'None'),
        ('quantity', 'Minimum Quantity Sold'),
        ('amount', 'Minimum Untaxed Amount Sold'),
        ('both', 'Both (Quantity and Amount)'),
        ('either', 'Either (Quantity or Amount)'),
    ], string='Target Type', default='none',
        help='Target requirement to be eligible for commission')
    min_qty = fields.Float(string='Minimum Quantity Sold', default=0.0,
                           help='Minimum quantity sold required to be eligible for commission')
    min_amount = fields.Monetary(string='Minimum Untaxed Amount Sold', default=0.0,
                                currency_field='currency_id',
                                help='Minimum untaxed amount sold required to be eligible for commission')
    commission_amount_type = fields.Selection([('percentage', 'Percentage'),
                                               ('fixed', 'Fixed Amount')],
                                              string="Amount Type",
                                              default='percentage',
                                              help='Commission amount type')
    fixed_amount = fields.Monetary('Commission Amount', default=0.0,
                                   help='Fixed Commission Amount')
    percentage = fields.Float(string='Rate in Percentage (%)',
                              help='Rate in percentage')
    amount = fields.Monetary('Maximum Commission Amount', default=0.0,
                             help='Maximum Commission Amount')
    currency_id = fields.Many2one("res.currency", string="Currency",
                                  default=lambda self:
                                  self.env.user.company_id.currency_id.id,
                                  help='Currency of the company')
    commission_id = fields.Many2one("crm.commission", string='Commission',
                                    help='Select The Crm Commission')

    @api.constrains('min_qty', 'min_amount')
    def _check_targets(self):
        """Ensure minimum targets are not negative"""
        for rec in self:
            if rec.min_qty < 0:
                raise exceptions.ValidationError(
                    _("The Minimum Quantity Sold cannot be negative."))
            if rec.min_amount < 0:
                raise exceptions.ValidationError(
                    _("The Minimum Untaxed Amount Sold cannot be negative."))

    def check_eligibility(self, total_qty, total_amount):
        """Check if sales meet the target requirements for commission eligibility"""
        self.ensure_one()
        if self.target_type == 'quantity':
            return total_qty >= self.min_qty
        elif self.target_type == 'amount':
            return total_amount >= self.min_amount
        elif self.target_type == 'both':
            return total_qty >= self.min_qty and total_amount >= self.min_amount
        elif self.target_type == 'either':
            return total_qty >= self.min_qty or total_amount >= self.min_amount
        return True

    @api.depends('category_id')
    def _onchange_category_id(self):
        """Function Sets the domain for selected category and removes
        the product if the product is not in the selected category"""
        for rec in self:
            rec.category_ids = rec.category_id.search(
                [('id', 'child_of', rec.category_id.ids)]).ids
            rec.product_id = None if rec.product_id.id not in self.env[
                'product.product'].search(
                [('categ_id', 'in',
                  rec.category_ids.ids)]).ids else rec.product_id.id
