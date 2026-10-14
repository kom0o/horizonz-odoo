# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpBreakdownCause(models.Model):
    _name = 'mrp.breakdown.cause'
    _description = 'Machine Breakdown Cause / سبب عطل الماكينة أو الخط'
    _order = 'legacy_code, name'

    name = fields.Char(string='Cause Description / سبب التوقف أو العطل', required=True, translate=True)
    legacy_code = fields.Integer(string='Legacy Code / الكود القديم', index=True)
    part_type = fields.Selection([
        ('mixer', 'الخلاطة (Mixer)'),
        ('press', 'المكبس (Press)'),
        ('extractor', 'الساحب (Extractor)'),
        ('grinder', 'الجلاية (Grinder)'),
        ('finger_car', 'الفنجر كار (Finger Car)'),
        ('line', 'الخط الناقل (Line Conveyor)'),
        ('doser', 'الدوزر (Doser)'),
        ('loader', 'الشيول (Loader)'),
        ('face_mixer', 'خلاطة الوجه (Face Mixer)'),
        ('block_machine', 'ماكينة الكبس (Block Press)'),
        ('forklift', 'الفوركلفت (Forklift)'),
        ('material', 'نقص خامات (Material Shortage)'),
        ('electric', 'كهرباء (Electrical)'),
        ('other', 'أخرى (Other)'),
    ], string='Machine Part / الجزء المتعطل', default='press')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Technical Details / تفاصيل فنية')
