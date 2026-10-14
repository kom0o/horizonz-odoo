# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class FinancialKpiTarget(models.Model):
    _name = 'financial.analyst.kpi.target'
    _description = 'KPI Target and Benchmarks'
    _order = 'group_code, sequence, name'

    name = fields.Char(string='اسم المؤشر', required=True)
    kpi_code = fields.Char(string='رمز المؤشر', required=True, index=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    group_code = fields.Selection([
        ('prof', 'الربحية'),
        ('exp', 'المصروفات والتكاليف'),
        ('grow', 'النمو'),
        ('liq', 'السيولة'),
        ('lev', 'الرفع المالي'),
        ('solv', 'الملاءة والأمان'),
        ('eff', 'الكفاءة التشغيلية والنشاط'),
        ('cf', 'التدفقات النقدية'),
        ('price', 'الأسعار والتكلفة'),
        ('spares', 'قطع الغيار'),
        ('ic', 'الشركات الشقيقة'),
    ], string='المجموعة', required=True, default='prof')

    company_id = fields.Many2one('res.company', string='الشركة (اتركه فارغاً للعام)', index=True)
    unit = fields.Selection([
        ('%', '%'),
        ('x', 'مرة (x)'),
        ('sar', 'ريال'),
        ('days', 'يوم'),
    ], string='الوحدة', default='%', required=True)

    direction = fields.Selection([
        ('up', 'الأعلى أفضل (≥)'),
        ('down', 'الأقل أفضل (≤)'),
    ], string='الاتجاه المستهدف', default='up', required=True)

    target_value = fields.Float(string='القيمة المستهدفة', required=True, digits=(16, 2))
    good_recommendation = fields.Text(string='التوصية عند تحقيق المستهدف')
    bad_recommendation = fields.Text(string='التوصية وخطة العمل عند التعثر')
    causes_text = fields.Text(string='الأسباب المحتملة (كل سبب في سطر)')

    _sql_constraints = [
        ('uniq_kpi_company', 'unique(kpi_code, company_id)', 'لا يمكن تكرار نفس المؤشر لنفس الشركة!')
    ]
