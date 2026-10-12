# -*- coding: utf-8 -*-
{
    'name': 'Construction Billing & Account Management',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Manage construction clients, sites, progress invoices, retention, payments, and due amounts',
    'description': """
Construction Billing & Account Management for Odoo 19 Community
================================================================
This module provides tailored financial workflows for construction companies:
- Construction Clients & Contractors profiling with credit limit and balance tracking.
- Construction Projects & Sites contract tracking with retention calculation.
- Progress Milestone Invoicing with Work Completion Certificate (WCC) and Retention Deduction.
- Project-linked Customer Payment receipts.
- Due & Overdue amount monitoring per project and customer.
    """,
    'author': 'Horizonz / ERP Architect',
    'website': 'https://horizonz.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'analytic',
        'mail',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'views/construction_project_views.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'views/account_payment_views.xml',
        'views/construction_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
