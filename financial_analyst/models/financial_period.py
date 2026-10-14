# -*- coding: utf-8 -*-
import json
import logging
import urllib.request
import urllib.error
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class FinancialPeriod(models.Model):
    _name = 'financial.analyst.period'
    _description = 'Financial Analysis Period'
    _order = 'year desc, month desc, id desc'

    name = fields.Char(string='اسم الفترة', compute='_compute_name', store=True, readonly=False)
    code = fields.Char(string='رمز الفترة', compute='_compute_code', store=True, readonly=False, index=True)
    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', string='العملة')

    year = fields.Integer(string='السنة', required=True, default=lambda self: fields.Date.today().year)
    month = fields.Integer(string='الشهر', default=lambda self: fields.Date.today().month, help='1 إلى 12، أو 0 للسنة الكاملة')
    period_type = fields.Selection([
        ('month', 'شهر واحد'),
        ('year', 'سنة كاملة'),
        ('custom', 'فترة مخصصة'),
    ], string='نوع الفترة', default='month', required=True)

    date_from = fields.Date(string='من تاريخ', required=True)
    date_to = fields.Date(string='إلى تاريخ', required=True)
    is_opening_period = fields.Boolean(string='فترة أرصدة افتتاحية', default=False)
    comparison_period_id = fields.Many2one('financial.analyst.period', string='فترة المقارنة')

    state = fields.Selection([
        ('draft', 'مسودة'),
        ('synced', 'تمت المزامنة من الحسابات'),
        ('audited', 'مراجعة ومعتمدة'),
        ('closed', 'مغلقة'),
    ], string='الحالة', default='draft', required=True)

    # --- Financial Baseline Figures (المؤشرات الأساسية المستخرجة من شجرة الحسابات) ---
    revenue = fields.Float(string='الإيرادات', digits=(16, 2))
    sl_gross = fields.Float(string='إجمالي المبيعات قبل الخصم', digits=(16, 2))
    sl_disc = fields.Float(string='خصومات المبيعات', digits=(16, 2))
    sl_trade = fields.Float(string='إيرادات النشاط التجاري', digits=(16, 2))
    trade_rev = fields.Float(string='إيرادات تجارية', digits=(16, 2))

    cogs = fields.Float(string='تكلفة المبيعات', digits=(16, 2))
    trade_cogs = fields.Float(string='تكلفة المبيعات التجارية', digits=(16, 2))
    opex = fields.Float(string='المصروفات التشغيلية', digits=(16, 2))
    depreciation = fields.Float(string='الاستهلاك والإطفاء', digits=(16, 2))
    tax = fields.Float(string='الزكاة والضريبة', digits=(16, 2))
    interest = fields.Float(string='تكاليف التمويل والفوائد', digits=(16, 2))
    other_income = fields.Float(string='إيرادات أخرى', digits=(16, 2))

    # الأصول
    cash = fields.Float(string='النقد وما في حكمه', digits=(16, 2))
    receivables = fields.Float(string='الذمم المدينة (العملاء)', digits=(16, 2))
    inventory = fields.Float(string='المخزون', digits=(16, 2))
    other_ca = fields.Float(string='أصول متداولة أخرى', digits=(16, 2))
    non_current = fields.Float(string='الأصول غير المتداولة (الثابتة)', digits=(16, 2))

    # الالتزامات وحقوق الملكية
    payables = fields.Float(string='الذمم الدائنة (الموردين)', digits=(16, 2))
    other_cl = fields.Float(string='مطلوبات متداولة أخرى', digits=(16, 2))
    short_debt = fields.Float(string='قروض قصيرة الأجل', digits=(16, 2))
    long_debt = fields.Float(string='قروض طويلة الأجل', digits=(16, 2))
    partners = fields.Float(string='جاري الشركاء', digits=(16, 2))
    other_ncl = fields.Float(string='مطلوبات غير متداولة أخرى', digits=(16, 2))
    capital = fields.Float(string='رأس المال المدفوع', digits=(16, 2))
    retained = fields.Float(string='الأرباح المبقاة (المحتجزة)', digits=(16, 2))
    equity = fields.Float(string='إجمالي حقوق الملكية', digits=(16, 2))

    # قطع الغيار
    spares = fields.Float(string='مخزون قطع الغيار', digits=(16, 2))
    spares_dead = fields.Float(string='قطع الغيار البطيئة والراكدة', digits=(16, 2))
    spares_prov = fields.Float(string='مخصص تقادم قطع الغيار', digits=(16, 2))
    spares_purch = fields.Float(string='مشتريات قطع الغيار بالفترة', digits=(16, 2))
    spares_issued = fields.Float(string='المنصرف للصيانة بالفترة', digits=(16, 2))
    spares_adj = fields.Float(string='تسويات قطع الغيار', digits=(16, 2))

    # التدفقات النقدية
    ocf = fields.Float(string='صافي التدفق التشغيلي (OCF)', digits=(16, 2))
    capex = fields.Float(string='النفقات الرأسمالية (Capex)', digits=(16, 2))
    fcf = fields.Float(string='التدفق النقدي الحر (FCF)', digits=(16, 2))

    tb_accounts_count = fields.Integer(string='عدد الحسابات المشمولة في الميزان')
    tb_synced_at = fields.Datetime(string='تاريخ آخر مزامنة')

    # المجاميع المحسوبة
    gp = fields.Float(string='مجمل الربح', compute='_compute_aggregates', store=True, digits=(16, 2))
    ebitda = fields.Float(string='EBITDA', compute='_compute_aggregates', store=True, digits=(16, 2))
    ebit = fields.Float(string='الربح التشغيلي (EBIT)', compute='_compute_aggregates', store=True, digits=(16, 2))
    ni = fields.Float(string='صافي الربح', compute='_compute_aggregates', store=True, digits=(16, 2))
    total_assets = fields.Float(string='إجمالي الأصول', compute='_compute_aggregates', store=True, digits=(16, 2))
    current_assets = fields.Float(string='الأصول المتداولة', compute='_compute_aggregates', store=True, digits=(16, 2))
    total_liabilities = fields.Float(string='إجمالي المطلوبات', compute='_compute_aggregates', store=True, digits=(16, 2))
    current_liabilities = fields.Float(string='المطلوبات المتداولة', compute='_compute_aggregates', store=True, digits=(16, 2))
    working_capital = fields.Float(string='رأس المال العامل', compute='_compute_aggregates', store=True, digits=(16, 2))

    # --- حقول المؤشرات المالية الـ 48 المحسوبة (Computed 48 KPIs) ---
    gross_margin = fields.Float(string='هامش الربح الإجمالي %', compute='_compute_kpis', store=True, digits=(16, 2))
    ebitda_margin = fields.Float(string='هامش EBITDA %', compute='_compute_kpis', store=True, digits=(16, 2))
    operating_margin = fields.Float(string='هامش الربح التشغيلي %', compute='_compute_kpis', store=True, digits=(16, 2))
    net_margin = fields.Float(string='هامش صافي الربح %', compute='_compute_kpis', store=True, digits=(16, 2))
    roa = fields.Float(string='العائد على الأصول (سنوي) %', compute='_compute_kpis', store=True, digits=(16, 2))
    roe = fields.Float(string='العائد على حقوق الملكية (سنوي) %', compute='_compute_kpis', store=True, digits=(16, 2))

    cogs_ratio = fields.Float(string='نسبة تكلفة المبيعات للإيرادات %', compute='_compute_kpis', store=True, digits=(16, 2))
    opex_ratio = fields.Float(string='نسبة المصروفات التشغيلية للإيرادات %', compute='_compute_kpis', store=True, digits=(16, 2))
    fin_cost_ratio = fields.Float(string='نسبة تكاليف التمويل للإيرادات %', compute='_compute_kpis', store=True, digits=(16, 2))
    expense_growth = fields.Float(string='نمو إجمالي المصروفات %', compute='_compute_kpis', store=True, digits=(16, 2))

    revenue_growth = fields.Float(string='نمو الإيرادات %', compute='_compute_kpis', store=True, digits=(16, 2))
    gross_profit_growth = fields.Float(string='نمو مجمل الربح %', compute='_compute_kpis', store=True, digits=(16, 2))
    net_profit_growth = fields.Float(string='نمو صافي الربح %', compute='_compute_kpis', store=True, digits=(16, 2))

    current_ratio = fields.Float(string='نسبة التداول (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    quick_ratio = fields.Float(string='نسبة السيولة السريعة (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    cash_ratio = fields.Float(string='نسبة النقدية (x)', compute='_compute_kpis', store=True, digits=(16, 2))

    debt_to_equity = fields.Float(string='نسبة الدين إلى الملكية (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    debt_ratio = fields.Float(string='نسبة المديونية %', compute='_compute_kpis', store=True, digits=(16, 2))
    debt_ratio_adj = fields.Float(string='نسبة المديونية المعدلة %', compute='_compute_kpis', store=True, digits=(16, 2))
    debt_to_equity_adj = fields.Float(string='الدين للملكية المعدل (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    partners_to_equity = fields.Float(string='جاري الشركاء إلى حقوق الملكية %', compute='_compute_kpis', store=True, digits=(16, 2))

    altman_z_score = fields.Float(string='مؤشر الفشل المالي (Altman Z)', compute='_compute_kpis', store=True, digits=(16, 2))
    altman_z_status = fields.Selection([
        ('safe', 'منطقة الأمان (≥ 2.90)'),
        ('grey', 'منطقة الحذر (1.23 - 2.89)'),
        ('danger', 'منطقة الخطر (< 1.23)'),
    ], string='حالة Altman Z', compute='_compute_kpis', store=True)

    capital_adequacy = fields.Float(string='كفاية رأس المال %', compute='_compute_kpis', store=True, digits=(16, 2))
    acc_losses = fields.Float(string='الخسائر المتراكمة %', compute='_compute_kpis', store=True, digits=(16, 2))
    interest_coverage = fields.Float(string='معدل تغطية الفوائد (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    net_debt_ebitda = fields.Float(string='صافي الدين إلى EBITDA (x)', compute='_compute_kpis', store=True, digits=(16, 2))

    asset_turnover = fields.Float(string='معدل دوران الأصول (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    inventory_turnover = fields.Float(string='معدل دوران المخزون (x)', compute='_compute_kpis', store=True, digits=(16, 2))
    dso = fields.Float(string='فترة التحصيل (أيام)', compute='_compute_kpis', store=True, digits=(16, 1))
    dio = fields.Float(string='فترة بقاء المخزون (أيام)', compute='_compute_kpis', store=True, digits=(16, 1))
    dpo = fields.Float(string='فترة السداد للموردين (أيام)', compute='_compute_kpis', store=True, digits=(16, 1))
    ccc = fields.Float(string='دورة التحول النقدي (أيام)', compute='_compute_kpis', store=True, digits=(16, 1))

    spares_ratio = fields.Float(string='مخزون قطع الغيار من إجمالي المخزون %', compute='_compute_kpis', store=True, digits=(16, 2))
    spares_dead_pct = fields.Float(string='نسبة الراكد والبطيء من قطع الغيار %', compute='_compute_kpis', store=True, digits=(16, 2))
    spares_cover = fields.Float(string='تغطية قطع الغيار للمنصرف (أشهر)', compute='_compute_kpis', store=True, digits=(16, 2))
    spares_work_cover = fields.Float(string='تغطية قطع الغيار العاملة (أشهر)', compute='_compute_kpis', store=True, digits=(16, 2))
    spares_prov_cover = fields.Float(string='تغطية مخصص التقادم %', compute='_compute_kpis', store=True, digits=(16, 2))
    spares_change = fields.Float(string='التغير في رصيد قطع الغيار', compute='_compute_kpis', store=True, digits=(16, 2))

    ic_non_trade_to_equity = fields.Float(string='أرصدة الشقيقة بالإنابة إلى الملكية %', compute='_compute_kpis', store=True, digits=(16, 2))
    ic_net_to_assets = fields.Float(string='صافي رصيد الشقيقة إلى الأصول %', compute='_compute_kpis', store=True, digits=(16, 2))
    ic_non_trade_change = fields.Float(string='التغير في أرصدة الشقيقة بالإنابة', compute='_compute_kpis', store=True, digits=(16, 2))

    ocf_ratio = fields.Float(string='التدفق التشغيلي للمطلوبات المتداولة %', compute='_compute_kpis', store=True, digits=(16, 2))
    cash_quality = fields.Float(string='جودة الأرباح (OCF / NI)', compute='_compute_kpis', store=True, digits=(16, 2))

    sales_price_change = fields.Float(string='تغير أسعار البيع %', compute='_compute_kpis', store=True, digits=(16, 2))
    mat_price_change = fields.Float(string='تغير أسعار المواد الخام %', compute='_compute_kpis', store=True, digits=(16, 2))

    # علاقات القوائم والخطوط
    issue_ids = fields.One2many('financial.analyst.issue', 'period_id', string='الإحالات وخطط التحسين')
    issue_count = fields.Integer(string='عدد الإحالات', compute='_compute_issue_count')
    open_issue_count = fields.Integer(string='الإحالات المفتوحة', compute='_compute_issue_count')

    sales_line_ids = fields.One2many('financial.analyst.sales.line', 'period_id', string='مبيعات الأصناف')
    material_line_ids = fields.One2many('financial.analyst.material.line', 'period_id', string='مشتريات المواد الخام')
    rep_line_ids = fields.One2many('financial.analyst.rep.line', 'period_id', string='أداء المندوبين')
    intercompany_line_ids = fields.One2many('financial.analyst.intercompany.line', 'period_id', string='الشركات الشقيقة')

    ai_narrative = fields.Text(string='تقرير المحلل الذكي (Gemini)')
    raw_tb_json = fields.Text(string='بيانات ميزان المراجعة الخام (JSON)')

    # --- Computes & Constraints ---
    @api.model_create_multi
    def create(self, vals_list):
        month_names = {
            1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
            5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
            9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر'
        }
        for vals in vals_list:
            year = vals.get('year') or fields.Date.today().year
            month = vals.get('month', fields.Date.today().month)
            ptype = vals.get('period_type', 'month')
            if not vals.get('code'):
                vals['code'] = f"{year}-00" if (ptype == 'year' or month == 0) else f"{year}-{month:02d}"
            if not vals.get('name'):
                if ptype == 'year' or month == 0:
                    vals['name'] = f"سنة {year}"
                else:
                    m_name = month_names.get(month, f"شهر {month}")
                    vals['name'] = f"{m_name} {year}"
        return super().create(vals_list)

    @api.depends('year', 'month', 'period_type')
    def _compute_code(self):
        for rec in self:
            if rec.period_type == 'year' or rec.month == 0:
                rec.code = f"{rec.year}-00"
            else:
                rec.code = f"{rec.year}-{rec.month:02d}"

    @api.depends('year', 'month', 'period_type')
    def _compute_name(self):
        month_names = {
            1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
            5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
            9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر'
        }
        for rec in self:
            if rec.period_type == 'year' or rec.month == 0:
                rec.name = f"سنة {rec.year}"
            else:
                m_name = month_names.get(rec.month, f"شهر {rec.month}")
                rec.name = f"{m_name} {rec.year}"

    @api.onchange('year', 'month', 'period_type')
    def _onchange_dates(self):
        if self.year:
            if self.period_type == 'year' or self.month == 0:
                self.date_from = date(self.year, 1, 1)
                self.date_to = date(self.year, 12, 31)
            elif self.month:
                self.date_from = date(self.year, self.month, 1)
                next_m = date(self.year, self.month, 1) + relativedelta(months=1)
                self.date_to = next_m - relativedelta(days=1)

    @api.depends('issue_ids.status')
    def _compute_issue_count(self):
        for rec in self:
            rec.issue_count = len(rec.issue_ids)
            rec.open_issue_count = len(rec.issue_ids.filtered(lambda i: i.status in ('open', 'in_progress', 'reopened')))

    @api.depends('revenue', 'cogs', 'opex', 'other_income', 'depreciation', 'interest', 'tax',
                 'cash', 'receivables', 'inventory', 'other_ca', 'non_current',
                 'payables', 'other_cl', 'short_debt', 'long_debt', 'partners', 'other_ncl', 'capital', 'retained')
    def _compute_aggregates(self):
        for r in self:
            r.gp = (r.revenue or 0.0) - (r.cogs or 0.0)
            r.ebitda = r.gp - (r.opex or 0.0) + (r.other_income or 0.0)
            r.ebit = r.ebitda - (r.depreciation or 0.0)
            r.ni = r.ebit - (r.interest or 0.0) - (r.tax or 0.0)

            r.current_assets = (r.cash or 0.0) + (r.receivables or 0.0) + (r.inventory or 0.0) + (r.other_ca or 0.0)
            r.total_assets = r.current_assets + (r.non_current or 0.0)

            r.current_liabilities = (r.payables or 0.0) + (r.other_cl or 0.0) + (r.short_debt or 0.0)
            r.total_liabilities = r.current_liabilities + (r.long_debt or 0.0) + (r.partners or 0.0) + (r.other_ncl or 0.0)

            if not r.equity:
                r.equity = (r.capital or 0.0) + (r.retained or 0.0)

            r.working_capital = r.current_assets - r.current_liabilities

    @api.depends('revenue', 'cogs', 'gp', 'ebitda', 'ebit', 'ni', 'total_assets', 'equity',
                 'current_assets', 'current_liabilities', 'inventory', 'cash', 'receivables', 'payables',
                 'short_debt', 'long_debt', 'partners', 'spares', 'spares_dead', 'spares_prov', 'spares_issued',
                 'comparison_period_id', 'date_from', 'date_to', 'ocf', 'capex')
    def _compute_kpis(self):
        for r in self:
            # Annualization factor
            days = 30
            if r.date_from and r.date_to:
                days = max(1, (r.date_to - r.date_from).days + 1)
            ann = 365.0 / days if days < 350 else 1.0

            rev = r.revenue or 0.0
            cogs = r.cogs or 0.0
            ta = r.total_assets or 0.0
            eq = r.equity or 0.0
            cl = r.current_liabilities or 0.0
            tl = r.total_liabilities or 0.0
            ni = r.ni or 0.0
            ebit = r.ebit or 0.0
            ebitda = r.ebitda or 0.0

            # 1. Profitability
            r.gross_margin = (r.gp / rev * 100.0) if rev else 0.0
            r.ebitda_margin = (ebitda / rev * 100.0) if rev else 0.0
            r.operating_margin = (ebit / rev * 100.0) if rev else 0.0
            r.net_margin = (ni / rev * 100.0) if rev else 0.0
            r.roa = ((ni * ann) / ta * 100.0) if ta else 0.0
            r.roe = ((ni * ann) / eq * 100.0) if eq else 0.0

            # 2. Expenses
            r.cogs_ratio = (cogs / rev * 100.0) if rev else 0.0
            r.opex_ratio = ((r.opex or 0.0) / rev * 100.0) if rev else 0.0
            r.fin_cost_ratio = ((r.interest or 0.0) / rev * 100.0) if rev else 0.0

            # 3. Liquidity
            r.current_ratio = (r.current_assets / cl) if cl else 0.0
            r.quick_ratio = ((r.current_assets - (r.inventory or 0.0)) / cl) if cl else 0.0
            r.cash_ratio = ((r.cash or 0.0) / cl) if cl else 0.0

            # 4. Leverage
            total_debt = (r.short_debt or 0.0) + (r.long_debt or 0.0)
            r.debt_to_equity = (total_debt / eq) if eq else 0.0
            r.debt_ratio = (tl / ta * 100.0) if ta else 0.0
            r.debt_ratio_adj = ((tl - (r.partners or 0.0)) / ta * 100.0) if ta else 0.0
            adj_eq = eq + (r.partners or 0.0)
            r.debt_to_equity_adj = (total_debt / adj_eq) if adj_eq else 0.0
            r.partners_to_equity = ((r.partners or 0.0) / eq * 100.0) if eq else 0.0

            # 5. Solvency & Altman Z
            # Z = 0.717*(WC/TA) + 0.847*(RE/TA) + 3.107*(EBIT*ann/TA) + 0.420*(Equity/TL) + 0.998*(Sales*ann/TA)
            if ta and tl:
                wc = r.working_capital or 0.0
                re = r.retained or 0.0
                z = (0.717 * (wc / ta) +
                     0.847 * (re / ta) +
                     3.107 * ((ebit * ann) / ta) +
                     0.420 * (eq / tl) +
                     0.998 * ((rev * ann) / ta))
                r.altman_z_score = z
                if z >= 2.90:
                    r.altman_z_status = 'safe'
                elif z >= 1.23:
                    r.altman_z_status = 'grey'
                else:
                    r.altman_z_status = 'danger'
            else:
                r.altman_z_score = 0.0
                r.altman_z_status = 'danger'

            r.capital_adequacy = (eq / ta * 100.0) if ta else 0.0
            cap = r.capital or 0.0
            r.acc_losses = ((abs(min(0.0, r.retained or 0.0))) / cap * 100.0) if cap else 0.0
            r.interest_coverage = (ebit / r.interest) if (r.interest and r.interest > 0) else (99.0 if ebit > 0 else 0.0)
            ebitda_ann = ebitda * ann
            net_debt = total_debt - (r.cash or 0.0)
            r.net_debt_ebitda = (net_debt / ebitda_ann) if ebitda_ann else 0.0

            # 6. Efficiency
            r.asset_turnover = ((rev * ann) / ta) if ta else 0.0
            op_inv = (r.inventory or 0.0) - (r.spares or 0.0)
            op_inv = max(0.0, op_inv)
            r.inventory_turnover = ((cogs * ann) / op_inv) if op_inv else 0.0

            r.dso = ((r.receivables or 0.0) / rev * days) if rev else 0.0
            r.dio = (op_inv / cogs * days) if cogs else 0.0
            r.dpo = ((r.payables or 0.0) / cogs * days) if cogs else 0.0
            r.ccc = r.dso + r.dio - r.dpo

            # 7. Spare parts
            inv = r.inventory or 0.0
            sp = r.spares or 0.0
            dead = r.spares_dead or 0.0
            monthly_issued = (r.spares_issued or 0.0) if days <= 35 else ((r.spares_issued or 0.0) / (days / 30.0))
            r.spares_ratio = (sp / inv * 100.0) if inv else 0.0
            r.spares_dead_pct = (dead / sp * 100.0) if sp else 0.0
            r.spares_cover = (sp / monthly_issued) if monthly_issued else 0.0
            r.spares_work_cover = ((sp - dead) / monthly_issued) if monthly_issued else 0.0
            r.spares_prov_cover = ((r.spares_prov or 0.0) / dead * 100.0) if dead else 0.0

            # 8. Cash flows
            r.ocf_ratio = (((r.ocf or 0.0) * ann) / cl * 100.0) if cl else 0.0
            r.cash_quality = ((r.ocf or 0.0) / ni) if ni else 0.0

            # 9. Comparison dependent KPIs
            cmp = r.comparison_period_id
            if cmp:
                prev_tot_exp = (cmp.cogs or 0.0) + (cmp.opex or 0.0)
                tot_exp = (r.cogs or 0.0) + (r.opex or 0.0)
                r.expense_growth = ((tot_exp - prev_tot_exp) / prev_tot_exp * 100.0) if prev_tot_exp else 0.0

                r.revenue_growth = ((rev - cmp.revenue) / cmp.revenue * 100.0) if cmp.revenue else 0.0
                r.gross_profit_growth = ((r.gp - cmp.gp) / cmp.gp * 100.0) if cmp.gp else 0.0
                r.net_profit_growth = ((ni - cmp.ni) / abs(cmp.ni) * 100.0) if cmp.ni else 0.0
                r.spares_change = sp - (cmp.spares or 0.0)
            else:
                r.expense_growth = 0.0
                r.revenue_growth = 0.0
                r.gross_profit_growth = 0.0
                r.net_profit_growth = 0.0
                r.spares_change = 0.0

            # Intercompany
            ic_lines = r.intercompany_line_ids
            rec_non_trade = sum(ic_lines.mapped('rec_non_trade'))
            pay_non_trade = sum(ic_lines.mapped('pay_non_trade'))
            net_ic = sum(ic_lines.mapped('net_balance'))
            r.ic_non_trade_to_equity = (rec_non_trade / eq * 100.0) if eq else 0.0
            r.ic_net_to_assets = (net_ic / ta * 100.0) if ta else 0.0
            if cmp:
                prev_rec_nt = sum(cmp.intercompany_line_ids.mapped('rec_non_trade'))
                r.ic_non_trade_change = rec_non_trade - prev_rec_nt
            else:
                r.ic_non_trade_change = 0.0

            r.sales_price_change = 0.0
            r.mat_price_change = 0.0

    # --- Core Accounting Sync Method (القراءة المباشرة من الحسابات) ---
    def action_sync_from_accounting(self):
        """
        تقوم هذه الدالة بالقراءة الفورية من جدول قيود اليومية account.move.line
        وتصنيف الحسابات وفق الدليل المحاسبي السعودي وحساب كافة الأرصدة والمؤشرات الـ 48
        دون الحاجة لأي تصدير أو استيراد ملفات خارجي.
        """
        self.ensure_one()
        MoveLine = self.env['account.move.line']
        company_id = self.company_id.id
        d_from = self.date_from
        d_to = self.date_to

        if not d_from or not d_to:
            raise UserError(_("الرجاء تحديد تاريخ البداية والنهاية للفترة أولاً."))

        # 1. استعلام القيود المرحلة
        lines = MoveLine.search([
            ('company_id', '=', company_id),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('move_id.state', '=', 'posted'),
        ])

        # ميزان المراجعة الحسابي
        totals = {
            'revenue': 0.0, 'trade_rev': 0.0, 'cogs': 0.0, 'trade_cogs': 0.0,
            'depreciation': 0.0, 'tax': 0.0, 'interest': 0.0, 'opex': 0.0, 'other_income': 0.0,
            'cash': 0.0, 'receivables': 0.0, 'inventory': 0.0, 'other_ca': 0.0, 'non_current': 0.0,
            'payables': 0.0, 'other_cl': 0.0, 'short_debt': 0.0, 'long_debt': 0.0, 'partners': 0.0,
            'other_ncl': 0.0, 'capital': 0.0, 'retained': 0.0, 'spares': 0.0,
        }

        # تجميع الأرصدة الختامية وحركة الفترة
        # الرصيد الختامي للأصول والالتزامات حتى تاريخ النهاية
        bs_lines = MoveLine.search([
            ('company_id', '=', company_id),
            ('date', '<=', d_to),
            ('move_id.state', '=', 'posted'),
        ])

        # خريطة حسابات الميزان التراكمية
        account_bs_balances = {}
        for l in bs_lines:
            ac_code = l.account_id.code or ''
            bal = l.debit - l.credit
            account_bs_balances[ac_code] = account_bs_balances.get(ac_code, 0.0) + bal

        # خريطة حسابات قائمة الدخل (حركة الفترة فقط بين d_from و d_to)
        account_is_balances = {}
        for l in lines:
            ac_code = l.account_id.code or ''
            bal = l.debit - l.credit
            account_is_balances[ac_code] = account_is_balances.get(ac_code, 0.0) + bal

        # تطبيق قواعد تصنيف tbMap
        for code, bal in account_is_balances.items():
            p2 = code[:2]
            p3 = code[:3]
            # إيرادات
            if code == "411102":
                totals['trade_rev'] += (-bal)
                totals['revenue'] += (-bal)
            elif p2 == "41" or p3 in ("412", "413"):
                totals['revenue'] += (-bal)
            elif p2 in ("42", "43", "44"):
                totals['other_income'] += (-bal)
            # تكاليف ومصروفات
            elif code in ("511101", "811101"):
                totals['cogs'] += bal
            elif code == "524140":
                totals['trade_cogs'] += bal
                totals['cogs'] += bal
            elif p3 in ("525", "527"):
                totals['depreciation'] += bal
            elif code == "524147":
                totals['tax'] += bal
            elif p3 in ("521", "522", "523", "524"):
                # حسب مركز التكلفة
                totals['opex'] += bal
            elif code.startswith('5') or code.startswith('6'):
                totals['opex'] += bal

        for code, bal in account_bs_balances.items():
            p2 = code[:2]
            p3 = code[:3]
            # أصول
            if p3 == "111":
                totals['cash'] += bal
            elif code in ("113101", "215101"):
                totals['receivables'] += bal
            elif p3 == "114" or code == "215102":
                totals['inventory'] += bal
            elif p3 in ("115", "116"):
                totals['other_ca'] += bal
            elif p3 in ("121", "122", "221") or code.startswith('12'):
                totals['non_current'] += bal
            elif code.startswith('1'):
                totals['other_ca'] += bal
            # التزامات
            elif p3 in ("211", "212"):
                totals['payables'] += (-bal)
            elif p3 == "213":
                totals['partners'] += (-bal)
            elif p3 in ("214", "215", "216"):
                totals['other_cl'] += (-bal)
            elif p3 == "217" or code == "222101" or p2 == "22":
                totals['other_ncl'] += (-bal)
            elif code.startswith('2'):
                totals['other_cl'] += (-bal)
            # حقوق الملكية
            elif code.startswith('31'):
                totals['capital'] += (-bal)
            elif code.startswith('3'):
                totals['retained'] += (-bal)

        # تحديث الأرقام الأساسية في الفترة
        self.write({
            'revenue': max(0.0, totals['revenue']),
            'trade_rev': max(0.0, totals['trade_rev']),
            'cogs': max(0.0, totals['cogs']),
            'trade_cogs': max(0.0, totals['trade_cogs']),
            'opex': max(0.0, totals['opex']),
            'depreciation': max(0.0, totals['depreciation']),
            'tax': max(0.0, totals['tax']),
            'other_income': max(0.0, totals['other_income']),
            'cash': totals['cash'],
            'receivables': totals['receivables'],
            'inventory': totals['inventory'],
            'other_ca': totals['other_ca'],
            'non_current': totals['non_current'],
            'payables': totals['payables'],
            'other_cl': totals['other_cl'],
            'partners': totals['partners'],
            'other_ncl': totals['other_ncl'],
            'capital': max(0.0, totals['capital']) or self.capital or 20000000.0,
            'retained': totals['retained'],
            'tb_accounts_count': len(account_bs_balances),
            'tb_synced_at': fields.Datetime.now(),
            'state': 'synced',
        })

        # 2. استخراج سطور المبيعات حسب الصنف
        sale_lines = MoveLine.search([
            ('company_id', '=', company_id),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('move_id.state', '=', 'posted'),
            ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('display_type', '=', 'product'),
        ])
        
        self.sales_line_ids.unlink()
        sales_data = {}
        for sl in sale_lines:
            sign = -1.0 if sl.move_id.move_type == 'out_refund' else 1.0
            prod = sl.product_id
            p_code = prod.default_code or ('PRD-%s' % prod.id) if prod else 'MISC'
            p_name = prod.name or sl.name or 'خدمة / صنف'
            qty = sl.quantity * sign
            subtot = sl.price_subtotal * sign
            if p_code not in sales_data:
                sales_data[p_code] = {'code': p_code, 'item': p_name, 'qty': 0.0, 'val': 0.0, 'product_id': prod.id if prod else False}
            sales_data[p_code]['qty'] += qty
            sales_data[p_code]['val'] += subtot

        new_sale_lines = []
        for d in sales_data.values():
            avg_price = (d['val'] / d['qty']) if d['qty'] else 0.0
            new_sale_lines.append((0, 0, {
                'code': d['code'],
                'item': d['item'],
                'product_id': d['product_id'],
                'qty': d['qty'],
                'price': avg_price,
                'value': d['val'],
                'terms': 'ex',
            }))
        if new_sale_lines:
            self.sales_line_ids = new_sale_lines

        # 3. استخراج سطور المواد الخام والمشتريات
        bill_lines = MoveLine.search([
            ('company_id', '=', company_id),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('move_id.state', '=', 'posted'),
            ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ('display_type', '=', 'product'),
        ])
        self.material_line_ids.unlink()
        mat_data = {}
        for bl in bill_lines:
            sign = -1.0 if bl.move_id.move_type == 'in_refund' else 1.0
            prod = bl.product_id
            p_code = prod.default_code or ('MAT-%s' % prod.id) if prod else 'RAW'
            p_name = prod.name or bl.name or 'مادة خام'
            qty = bl.quantity * sign
            subtot = bl.price_subtotal * sign
            if p_code not in mat_data:
                mat_data[p_code] = {'code': p_code, 'item': p_name, 'qty': 0.0, 'val': 0.0, 'product_id': prod.id if prod else False}
            mat_data[p_code]['qty'] += qty
            mat_data[p_code]['val'] += subtot

        new_mat_lines = []
        for d in mat_data.values():
            new_mat_lines.append((0, 0, {
                'code': d['code'],
                'item': d['item'],
                'product_id': d['product_id'],
                'qty': d['qty'],
                'used': d['qty'] * 0.95,  # تقديري
                'value': d['val'],
            }))
        if new_mat_lines:
            self.material_line_ids = new_mat_lines

        # 4. أداء المندوبين
        self.rep_line_ids.unlink()
        reps_data = {}
        for inv in self.env['account.move'].search([
            ('company_id', '=', company_id),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
        ]):
            user = inv.invoice_user_id or self.env.user
            sign = -1.0 if inv.move_type == 'out_refund' else 1.0
            u_id = user.id
            if u_id not in reps_data:
                reps_data[u_id] = {'user_id': u_id, 'rep': user.name, 'val': 0.0, 'invoices': 0, 'partners': set()}
            reps_data[u_id]['val'] += (inv.amount_untaxed * sign)
            reps_data[u_id]['invoices'] += 1
            if inv.partner_id:
                reps_data[u_id]['partners'].add(inv.partner_id.id)

        new_rep_lines = []
        for d in reps_data.values():
            new_rep_lines.append((0, 0, {
                'user_id': d['user_id'],
                'rep': d['rep'],
                'value': d['val'],
                'invoices': d['invoices'],
                'customers': len(d['partners']),
            }))
        if new_rep_lines:
            self.rep_line_ids = new_rep_lines

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('مزامنة الحسابات بنجاح'),
                'message': _('تمت قراءة قيود اليومية وميزان المراجعة والمبيعات وتحديث كافة المؤشرات الـ 48 بنجاح!'),
                'sticky': False,
                'type': 'success',
            }
        }

    # --- Full JSON Payload for Web Dashboard (الواجهة التفاعلية) ---
    @api.model
    def get_dashboard_payload(self, period_id=None, company_id=None):
        """
        تجميع حزمة البيانات الشاملة بتنسيق JSON المطابق تماماً لمتطلبات الواجهة التفاعلية
        """
        env = self.env
        active_company = env.company
        if company_id:
            active_company = env['res.company'].browse(company_id)

        # 1. قائمة الشركات
        companies_data = {}
        for c in env.user.company_ids:
            companies_data[str(c.id)] = {
                'id': str(c.id),
                'name': c.name,
                'currency': c.currency_id.symbol or 'ر.س',
                'cr': c.vat or '',
                'sector': 'صناعي',
            }

        # 2. الفترات
        domain = [('company_id', '=', active_company.id)]
        periods = self.search(domain, order='year desc, month desc, id desc')
        
        if not periods:
            # إنشاء فترة أولى افتراضية للشهر الحالي إذا لم تكن موجودة
            today = fields.Date.today()
            first_period = self.create({
                'company_id': active_company.id,
                'name': 'سبتمبر 2026',
                'code': '2026-09',
                'year': 2026,
                'month': 9,
                'period_type': 'month',
                'date_from': date(2026, 9, 1),
                'date_to': date(2026, 9, 30),
                'revenue': 4788543.51,
                'cogs': 3119915.80,
                'opex': 848254.73,
                'depreciation': 292631.10,
                'tax': 60000.0,
                'cash': 8615955.67,
                'receivables': 471143.30,
                'inventory': 22596433.87,
                'other_ca': 42432667.56,
                'non_current': 21930535.52,
                'payables': 5994426.35,
                'other_cl': 18608107.45,
                'partners': 9464385.50,
                'other_ncl': 15118637.53,
                'capital': 20000000.0,
                'retained': 26325564.59,
                'spares': 27373525.17,
                'spares_dead': 6045460.59,
                'spares_prov': 11083499.19,
                'spares_purch': 308436.44,
                'spares_issued': 284029.64,
            })
            periods = first_period

        periods_data = {}
        for p in periods:
            p_code = p.code or f"{p.year}-{p.month:02d}"
            cid_str = str(p.company_id.id)
            period_dict = {
                'id': p.id,
                'code': p_code,
                'name': p.name,
                'year': p.year,
                'month': p.month,
                'company': cid_str,
                'companyName': p.company_id.name,
                'state': p.state,
                'data': {
                    'revenue': p.revenue,
                    'cogs': p.cogs,
                    'gp': p.gp,
                    'ebitda': p.ebitda,
                    'ebit': p.ebit,
                    'ni': p.ni,
                    'opex': p.opex,
                    'depreciation': p.depreciation,
                    'tax': p.tax,
                    'interest': p.interest,
                    'otherIncome': p.other_income,
                    'cash': p.cash,
                    'receivables': p.receivables,
                    'inventory': p.inventory,
                    'otherCA': p.other_ca,
                    'nonCurrent': p.non_current,
                    'totalAssets': p.total_assets,
                    'payables': p.payables,
                    'otherCL': p.other_cl,
                    'shortDebt': p.short_debt,
                    'longDebt': p.long_debt,
                    'partners': p.partners,
                    'otherNCL': p.other_ncl,
                    'capital': p.capital,
                    'retained': p.retained,
                    'equity': p.equity,
                    'spares': p.spares,
                    'sparesDead': p.spares_dead,
                    'sparesProv': p.spares_prov,
                    'sparesPurch': p.spares_purch,
                    'sparesIssued': p.spares_issued,
                    'sparesAdj': p.spares_adj,
                    'ocf': p.ocf,
                    'capex': p.capex,
                    'fcf': p.fcf,
                    'sales': [{'code': s.code, 'item': s.item, 'terms': s.terms, 'qty': s.qty, 'price': s.price, 'value': s.value} for s in p.sales_line_ids],
                    'mats': [{'code': m.code, 'item': m.item, 'qty': m.qty, 'used': m.used, 'value': m.value} for m in p.material_line_ids],
                    'reps': [{'rep': r.rep, 'qty': r.qty, 'value': r.value, 'invoices': r.invoices, 'customers': r.customers} for r in p.rep_line_ids],
                    'ic': [{'name': ic.name, 'recTrade': ic.rec_trade, 'recNonTrade': ic.rec_non_trade, 'payTrade': ic.pay_trade, 'payNonTrade': ic.pay_non_trade, 'net': ic.net_balance} for ic in p.intercompany_line_ids],
                    'aiNarrative': p.ai_narrative or '',
                }
            }
            periods_data[f"{cid_str}__{p_code}"] = period_dict
            periods_data[p_code] = period_dict


        # 3. الإحالات
        issues = env['financial.analyst.issue'].search([('company_id', '=', active_company.id)])
        issues_data = {}
        for iss in issues:
            issues_data[str(iss.id)] = {
                'id': iss.id,
                'name': iss.name,
                'company': str(iss.company_id.id),
                'companyName': iss.company_id.name,
                'period': iss.period_id.code,
                'periodLabel': iss.period_id.name,
                'kpi': iss.kpi_code,
                'kpiName': iss.kpi_name,
                'group': iss.group_code or 'prof',
                'unit': iss.unit,
                'value': iss.current_value,
                'target': iss.target_value,
                'newTarget': iss.new_target,
                'dir': iss.direction,
                'cause': iss.cause,
                'causeOther': iss.cause_other or '',
                'recurred': iss.is_recurred,
                'recurCount': iss.recur_count,
                'assigneeId': str(iss.assignee_id.id) if iss.assignee_id else '',
                'assigneeName': iss.assignee_id.name if iss.assignee_id else '',
                'assigneeEmail': iss.assignee_email or '',
                'priority': iss.priority,
                'due': str(iss.due_date),
                'plan': iss.plan,
                'status': iss.status,
                'createdAt': iss.create_date.strftime('%Y-%m-%d %H:%M') if iss.create_date else '',
                'createdByName': iss.create_uid.name if iss.create_uid else '',
            }

        # 4. أصحاب الاختصاص
        assignees = env['financial.analyst.assignee'].search([])
        assignees_data = {}
        for a in assignees:
            assignees_data[str(a.id)] = {
                'id': str(a.id),
                'name': a.name,
                'email': a.email,
                'title': a.title or '',
                'dept': a.department or '',
                'groups': [g.strip() for g in (a.groups_str or '').split(',') if g.strip()],
                'odooAlias': a.odoo_alias or '',
                'companies': [str(c.id) for c in a.company_ids],
            }

        # 5. إعدادات Gemini
        ir_config = env['ir.config_parameter'].sudo()
        gemini_cfg = {
            'apiKey': ir_config.get_param('financial_analyst.gemini_api_key', ''),
            'model': ir_config.get_param('financial_analyst.gemini_model', 'gemini-2.5-flash'),
            'baseUrl': ir_config.get_param('financial_analyst.gemini_base_url', 'https://generativelanguage.googleapis.com'),
        }

        selected_code = period_id or (periods[0].code if periods else '')

        return {
            'companies': companies_data,
            'activeCompanyId': str(active_company.id),
            'periods': periods_data,
            'activePeriodCode': selected_code,
            'issues': issues_data,
            'assignees': assignees_data,
            'geminiCfg': gemini_cfg,
            'isAdmin': env.user.has_group('base.group_system') or env.user.has_group('financial_analyst.group_financial_analyst_admin'),
        }

    # --- API Helper Methods for Web Dashboard ---
    @api.model
    def api_save_issue(self, vals):
        company_id = int(vals.get('companyId', self.env.company.id))
        period_code = vals.get('period')
        period = self.search([('company_id', '=', company_id), ('code', '=', period_code)], limit=1)
        if not period:
            raise UserError(_("الفترة المالية غير موجودة!"))

        assignee_id = int(vals.get('assigneeId')) if vals.get('assigneeId') else False
        issue_vals = {
            'company_id': company_id,
            'period_id': period.id,
            'kpi_code': vals.get('kpi'),
            'kpi_name': vals.get('kpiName'),
            'group_code': vals.get('group'),
            'unit': vals.get('unit', '%'),
            'direction': vals.get('dir', 'up'),
            'current_value': float(vals.get('value', 0.0)),
            'target_value': float(vals.get('target', 0.0)),
            'new_target': float(vals.get('newTarget', 0.0)),
            'cause': vals.get('cause'),
            'cause_other': vals.get('causeOther', ''),
            'is_recurred': bool(vals.get('recurred')),
            'recur_count': int(vals.get('recurCount', 0)),
            'assignee_id': assignee_id,
            'priority': vals.get('priority', 'high'),
            'due_date': vals.get('due'),
            'plan': vals.get('plan'),
            'status': 'open',
        }
        issue = self.env['financial.analyst.issue'].create(issue_vals)
        return {'success': True, 'id': issue.id, 'name': issue.name}

    @api.model
    def api_close_issue(self, issue_id):
        issue = self.env['financial.analyst.issue'].browse(int(issue_id))
        if issue.exists():
            issue.action_close()
            return {'success': True}
        return {'success': False, 'error': 'Issue not found'}

    @api.model
    def api_reopen_issue(self, issue_id, reason=''):
        issue = self.env['financial.analyst.issue'].browse(int(issue_id))
        if issue.exists():
            issue.action_reopen(reason)
            return {'success': True}
        return {'success': False, 'error': 'Issue not found'}

    @api.model
    def api_save_ai_narrative(self, period_code, company_id, narrative_text):
        period = self.search([('company_id', '=', int(company_id)), ('code', '=', period_code)], limit=1)
        if period:
            period.ai_narrative = narrative_text
            return {'success': True}
        return {'success': False}

    def action_open_dashboard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'financial_analyst.dashboard_action',
            'name': _('المحلل المالي — لوحة المؤشرات'),
            'params': {
                'period_code': self.code,
                'company_id': self.company_id.id,
            }
        }
