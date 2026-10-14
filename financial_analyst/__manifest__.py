# -*- coding: utf-8 -*-
{
    'name': 'المحلل المالي — لوحة المؤشرات والتحليل المالي المتقدم',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'لوحة تحكم تفاعلية للمؤشرات المالية الـ 48، ومؤشر Altman Z للفشل المالي، ومقارنة الفترات، والإحالات مع القراءة المباشرة من الحسابات',
    'description': """
المحلل المالي المتقدم — Odoo Custom Module
=============================================
تحويل وتكامل حزمة المحلل المالي (إصدار 79) داخل نظام أودو بالكامل:
- قراءة مباشرة ولحظية من قيود اليومية وميزان المراجعة (account.move.line).
- احتساب 48 مؤشر مالي عبر 11 مجموعة مع المستهدفات والألوان التفاعلية.
- مؤشر Altman Z-Score للتنبؤ بالتعثر المالي وتصنيف مناطق الأمان والخطر.
- مقارنة الفترات المالية والاتجاهات الزمنية التاريخية.
- مراجعة الميزان، الأسعار والتكلفة، أداء المندوبين، قطع الغيار، والشركات الشقيقة.
- قائمة التدفقات النقدية التشغيلية والاستثمارية والتمويلية والتدفق الحر FCF.
- دورة عمل متكاملة لإحالات المؤشرات وخطط التحسين مع سجل المحادثات (Chatter).
- تكامل ذكي مع Google Gemini لتوليد التقارير المالية واقتراح خطط التحسين.
    """,
    'author': 'Horizonz / ERP Architect & Developer',
    'website': 'https://horizonz.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'analytic',
        'mail',
        'web',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/default_kpi_data.xml',
        'views/financial_issue_views.xml',
        'views/financial_period_views.xml',
        'views/financial_target_and_assignee_views.xml',
        'views/res_config_settings_views.xml',
        'views/financial_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'financial_analyst/static/src/lib/chart.umd.min.js',
            'financial_analyst/static/src/lib/xlsx.full.min.js',
            'financial_analyst/static/src/css/financial_dashboard.css',
            'financial_analyst/static/src/xml/financial_dashboard.xml',
            'financial_analyst/static/src/js/financial_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
