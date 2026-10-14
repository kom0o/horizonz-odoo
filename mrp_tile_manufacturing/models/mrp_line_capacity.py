# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpLineCapacity(models.Model):
    _name = 'mrp.line.capacity'
    _description = 'Workcenter Production Norm & Capacity / معايير الطاقات الإنتاجية للخط'
    _order = 'workcenter_id, product_id'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Production Line / خط الإنتاج', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product / الصنف', required=True, ondelete='cascade')
    moulds_count = fields.Integer(string='Mould Cavities / عدد عيون القالب', default=1)
    units_per_sqm = fields.Float(string='Units per SQM / عدد البلاطات في المتر المربع', digits=(12, 2))
    standard_press_per_hour = fields.Float(string='Std Press Speed (m²/hr) / معيار إنتاج الكبس بالساعة', digits=(12, 2))
    standard_grinder_per_hour = fields.Float(string='Std Grinding Speed (m²/hr) / معيار إنتاج الجلي بالساعة', digits=(12, 2))
    steam_curing_hours = fields.Float(string='Steam Curing (Hours) / ساعات التبخير والمعالجة', default=12.0)
    standard_waste_percent = fields.Float(string='Std Waste (%) / نسبة الهالك المسموحة معيارياً', default=3.0)
    notes = fields.Char(string='Notes / ملاحظات')

    _sql_constraints = [
        ('workcenter_product_uniq', 'unique(workcenter_id, product_id)', 'Standard capacity is already defined for this product on this line!')
    ]
