# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class MrpShiftLog(models.Model):
    _name = 'mrp.shift.log'
    _description = 'Daily Shift Production Sheet / ورقة تشغيل الوردية اليومية'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Sheet Reference / الرقم المرجعي', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    date = fields.Date(string='Production Date / تاريخ الإنتاج', required=True, default=fields.Date.context_today, tracking=True)
    shift = fields.Selection([
        ('morning', 'Morning Shift (الوردية الصباحية)'),
        ('evening', 'Evening Shift (الوردية المسائية)'),
    ], string='Shift / الوردية', required=True, default='morning', tracking=True)
    shift_status = fields.Selection([
        ('continuous', 'Continuous Operation (تشغيل مستمر)'),
        ('cleaning', 'Cleaning & Flush (تصفية وتنظيف)'),
        ('opening', 'Opening Balance (رصيد إفتتاحي)'),
    ], string='Shift Mode / حالة التشغيل', default='continuous', tracking=True)
    supervisor_id = fields.Many2one('res.users', string='Shift Supervisor / مشرف الوردية', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', string='Company / الشركة', default=lambda self: self.env.company, required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Plant / Factory / المصنع', tracking=True)

    scheduled_hours = fields.Float(string='Shift Duration (Hrs) / ساعات الوردية', default=12.0)
    maintenance_hours = fields.Float(string='Scheduled Maintenance (Hrs) / ساعات الصيانة المخططة', default=1.5)
    rest_hours = fields.Float(string='Breaks & Shift Change (Hrs) / استراحة وتبديل وردية', default=0.75)
    net_available_hours = fields.Float(string='Net Operating Target (Hrs) / صافي ساعات التشغيل المستهدفة', compute='_compute_net_hours', store=True)

    state = fields.Selection([
        ('draft', 'Draft (مسودة)'),
        ('confirmed', 'In Progress (قيد التشغيل)'),
        ('done', 'Done / Approved (معتمد ومرحل)'),
        ('cancel', 'Cancelled (ملغي)'),
    ], string='Status / الحالة', default='draft', tracking=True)

    press_line_ids = fields.One2many('mrp.shift.log.press', 'shift_log_id', string='Press Operations / مخرجات الكبس')
    grinder_line_ids = fields.One2many('mrp.shift.log.grinder', 'shift_log_id', string='Grinder Operations / مخرجات الجلي والفرز')
    breakdown_ids = fields.One2many('mrp.shift.log.breakdown', 'shift_log_id', string='Breakdowns & Stoppages / الأعطال والتوقفات')

    # Aggregated KPI Summary
    total_press_sqm = fields.Float(string='Total Press (m²) / إجمالي الكبس', compute='_compute_totals', store=True)
    total_grinder_sqm = fields.Float(string='Total Grinded (m²) / إجمالي الجلي', compute='_compute_totals', store=True)
    total_first_quality_sqm = fields.Float(string='First Quality (m²) / فرز أول ممتاز', compute='_compute_totals', store=True)
    total_second_quality_sqm = fields.Float(string='Second Quality (m²) / فرز ثاني', compute='_compute_totals', store=True)
    total_skirting_sqm = fields.Float(string='Skirting (m²) / وزرة', compute='_compute_totals', store=True)
    total_regrind_sqm = fields.Float(string='Regrinding (m²) / إعادة جلي', compute='_compute_totals', store=True)
    total_waste_sqm = fields.Float(string='Total Waste (m²) / إجمالي الهالك والكسر', compute='_compute_totals', store=True)
    total_breakdown_hours = fields.Float(string='Breakdown Time (Hrs) / إجمالي ساعات التوقف', compute='_compute_totals', store=True)
    avg_waste_percent = fields.Float(string='Actual Waste (%) / نسبة الهالك الفعلية', compute='_compute_totals', store=True)
    quality_yield_percent = fields.Float(string='First Quality Yield (%) / كفاءة النخب الأول', compute='_compute_totals', store=True)

    notes = fields.Html(string='Remarks / ملاحظات الوردية')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.shift.log') or _('New')
        return super(MrpShiftLog, self).create(vals_list)

    @api.depends('scheduled_hours', 'maintenance_hours', 'rest_hours')
    def _compute_net_hours(self):
        for rec in self:
            rec.net_available_hours = max(0.0, rec.scheduled_hours - rec.maintenance_hours - rec.rest_hours)

    @api.depends(
        'press_line_ids.actual_press_sqm',
        'grinder_line_ids.total_grinded_sqm',
        'grinder_line_ids.first_quality_sqm',
        'grinder_line_ids.second_quality_sqm',
        'grinder_line_ids.skirting_sqm',
        'grinder_line_ids.regrind_sqm',
        'grinder_line_ids.waste_sqm',
        'breakdown_ids.duration_hours'
    )
    def _compute_totals(self):
        for rec in self:
            total_press = sum(rec.press_line_ids.mapped('actual_press_sqm'))
            total_grind = sum(rec.grinder_line_ids.mapped('total_grinded_sqm'))
            first_q = sum(rec.grinder_line_ids.mapped('first_quality_sqm'))
            second_q = sum(rec.grinder_line_ids.mapped('second_quality_sqm'))
            skirting = sum(rec.grinder_line_ids.mapped('skirting_sqm'))
            regrind = sum(rec.grinder_line_ids.mapped('regrind_sqm'))
            waste = sum(rec.grinder_line_ids.mapped('waste_sqm'))
            breakdown_hrs = sum(rec.breakdown_ids.mapped('duration_hours'))

            rec.total_press_sqm = total_press
            rec.total_grinder_sqm = total_grind
            rec.total_first_quality_sqm = first_q
            rec.total_second_quality_sqm = second_q
            rec.total_skirting_sqm = skirting
            rec.total_regrind_sqm = regrind
            rec.total_waste_sqm = waste
            rec.total_breakdown_hours = breakdown_hrs

            if total_grind > 0:
                rec.avg_waste_percent = (waste / total_grind) * 100.0
                rec.quality_yield_percent = (first_q / total_grind) * 100.0
            else:
                rec.avg_waste_percent = 0.0
                rec.quality_yield_percent = 0.0

    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'

    def action_done(self):
        for rec in self:
            for g_line in rec.grinder_line_ids:
                sum_parts = g_line.first_quality_sqm + g_line.second_quality_sqm + g_line.skirting_sqm + g_line.regrind_sqm + g_line.waste_sqm
                if abs(sum_parts - g_line.total_grinded_sqm) > 0.01 and g_line.total_grinded_sqm > 0:
                    raise ValidationError(_(
                        "Grinder Line '%s' Quality distribution mismatch!\nTotal Grinded (%s m²) does not equal sum of parts (%s m²)."
                    ) % (g_line.workcenter_id.name, g_line.total_grinded_sqm, sum_parts))
            rec.state = 'done'

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancel'


class MrpShiftLogPress(models.Model):
    _name = 'mrp.shift.log.press'
    _description = 'Shift Pressing Operation Detail / تفاصيل تشغيل الكبس للخط'
    _order = 'shift_log_id, workcenter_id'

    shift_log_id = fields.Many2one('mrp.shift.log', string='Shift Log', required=True, ondelete='cascade')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Line / خط الإنتاج', required=True)
    product_id = fields.Many2one('product.product', string='Product / الصنف', required=True)
    shift_hours = fields.Float(string='Shift Hours / ساعات الوردية', default=12.0)
    breakdown_hours = fields.Float(string='Breakdown (Hrs) / توقفات المكبس', default=0.0)
    operating_hours = fields.Float(string='Net Operating (Hrs) / صافي ساعات الكبس', compute='_compute_hours', store=True)

    standard_rate_hour = fields.Float(string='Std Rate (m²/h) / المعيار بالساعة', compute='_compute_standard_rate', store=True)
    actual_press_sqm = fields.Float(string='Actual Press (m²) / الإنتاج الفعلي', required=True, default=0.0)
    expected_press_sqm = fields.Float(string='Expected Press (m²) / الإنتاج المتوقع', compute='_compute_expected_press', store=True)
    efficiency_rate = fields.Float(string='Efficiency (%) / كفاءة الكبس', compute='_compute_expected_press', store=True)

    @api.depends('shift_hours', 'breakdown_hours')
    def _compute_hours(self):
        for rec in self:
            rec.operating_hours = max(0.0, rec.shift_hours - rec.breakdown_hours)

    @api.depends('workcenter_id', 'product_id')
    def _compute_standard_rate(self):
        for rec in self:
            if rec.workcenter_id and rec.product_id:
                cap = self.env['mrp.line.capacity'].search([
                    ('workcenter_id', '=', rec.workcenter_id.id),
                    ('product_id', '=', rec.product_id.id)
                ], limit=1)
                rec.standard_rate_hour = cap.standard_press_per_hour if cap else 0.0
            else:
                rec.standard_rate_hour = 0.0

    @api.depends('operating_hours', 'standard_rate_hour', 'actual_press_sqm')
    def _compute_expected_press(self):
        for rec in self:
            rec.expected_press_sqm = rec.operating_hours * rec.standard_rate_hour
            if rec.expected_press_sqm > 0:
                rec.efficiency_rate = (rec.actual_press_sqm / rec.expected_press_sqm) * 100.0
            else:
                rec.efficiency_rate = 0.0


class MrpShiftLogGrinder(models.Model):
    _name = 'mrp.shift.log.grinder'
    _description = 'Shift Grinding & Quality Grading / تشغيل الجلي وتصنيف الجودة والفرز'
    _order = 'shift_log_id, workcenter_id'

    shift_log_id = fields.Many2one('mrp.shift.log', string='Shift Log', required=True, ondelete='cascade')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Grinder / الجلاية', required=True)
    product_id = fields.Many2one('product.product', string='Product / الصنف', required=True)
    shift_hours = fields.Float(string='Shift Hours / ساعات الوردية', default=12.0)
    breakdown_hours = fields.Float(string='Breakdown (Hrs) / توقفات الجلاية', default=0.0)

    # Multi-tier Sorting (m²)
    first_quality_sqm = fields.Float(string='1st Quality (m²) / فرز أول ممتاز', default=0.0)
    second_quality_sqm = fields.Float(string='2nd Quality (m²) / فرز ثاني', default=0.0)
    skirting_sqm = fields.Float(string='Skirting (m²) / وزرة', default=0.0)
    regrind_sqm = fields.Float(string='Regrinding (m²) / إعادة جلي', default=0.0)
    waste_sqm = fields.Float(string='Waste (m²) / هالك وكسر', default=0.0)

    total_grinded_sqm = fields.Float(string='Total Grinded (m²) / إجمالي الجلي', compute='_compute_grinder_totals', store=True)
    waste_percent = fields.Float(string='Waste (%) / نسبة الهالك', compute='_compute_grinder_totals', store=True)
    is_waste_exceeded = fields.Boolean(string='Waste Exceeded 3%', compute='_compute_grinder_totals', store=True)

    @api.depends('first_quality_sqm', 'second_quality_sqm', 'skirting_sqm', 'regrind_sqm', 'waste_sqm')
    def _compute_grinder_totals(self):
        for rec in self:
            total = rec.first_quality_sqm + rec.second_quality_sqm + rec.skirting_sqm + rec.regrind_sqm + rec.waste_sqm
            rec.total_grinded_sqm = total
            if total > 0:
                w_pct = (rec.waste_sqm / total) * 100.0
                rec.waste_percent = w_pct
                rec.is_waste_exceeded = w_pct > 3.0
            else:
                rec.waste_percent = 0.0
                rec.is_waste_exceeded = False


class MrpShiftLogBreakdown(models.Model):
    _name = 'mrp.shift.log.breakdown'
    _description = 'Shift Machine Breakdown & Stoppage / سجل توقفات وأعطال الوردية'
    _order = 'shift_log_id, workcenter_id'

    shift_log_id = fields.Many2one('mrp.shift.log', string='Shift Log', required=True, ondelete='cascade')
    date = fields.Date(string='Date / التاريخ', related='shift_log_id.date', store=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Machine / Line / الماكينة أو الخط', required=True)
    equipment_part = fields.Selection([
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
    ], string='Equipment Part / الجزء المتعطل', default='press', required=True)
    cause_id = fields.Many2one('mrp.breakdown.cause', string='Cause / سبب العطل أو التوقف', required=True)
    duration_hours = fields.Float(string='Stoppage Duration (Hrs) / مدة التوقف بالساعات', required=True, default=0.5)
    maintenance_request_id = fields.Many2one('maintenance.request', string='Maintenance Order / أمر الصيانة')
    notes = fields.Char(string='Notes / ملاحظات')

    def action_create_maintenance_request(self):
        for rec in self:
            if not rec.maintenance_request_id:
                m_req = self.env['maintenance.request'].create({
                    'name': f"{rec.workcenter_id.name} - {rec.cause_id.name}",
                    'description': f"Breakdown on {rec.date} during {rec.shift_log_id.shift}. Duration: {rec.duration_hours} hrs. Part: {rec.equipment_part}. Cause: {rec.cause_id.name}",
                    'priority': '2',
                    'request_date': rec.date or fields.Date.context_today(self),
                })
                rec.maintenance_request_id = m_req.id
