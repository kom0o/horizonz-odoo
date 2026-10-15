# -*- coding: utf-8 -*-
{
    'name': 'IT Asset Management & Digital Custody',
    'version': '18.0.1.0.0',
    'category': 'Operations/IT Assets',
    'summary': 'Hardware Inventory, Employee Custody Handovers, Returns, Disposals, Credentials & WhatsApp Approvals',
    'description': """
IT Asset Management & Digital Custody for Odoo 18 Community
===========================================================
A complete, native replacement for Studio-built IT asset systems:
- **Asset Master**: Hardware specs (CPU, RAM, NVMe/SSD/HDD, Serial No, Model/SKU), OS, Software, Warranty, Financials.
- **Kanban Pipeline**: Stock, Assigned, Scrap, Sold stages with color-coded tracking.
- **Custody Assignment (تسليم العهدة)**: Bundle main computer + monitor + peripherals. Auto-reassignment conflict resolution.
- **Digital Approvals & n8n Integration**: Webhook trigger for WhatsApp confirmation & callback receiver endpoint.
- **Return & Clearance (استرجاع العهدة / إخلاء طرف)**: Auto-restoration of assets back into available Stock.
- **Disposal & Scrap (التخريد والاستبعاد)**: Price-aware automatic disposition (0 SAR -> Scrap, >0 SAR -> Sold).
- **IT Credentials Vault**: Encrypted access management for servers, tools, and licenses.
- **Official Bilingual PDF Reports**: "IT ASSET ISSUE FORM" and "IT ASSET RETURN FORM" (Arabic/English).
    """,
    'author': 'Custom IT Solutions',
    'website': 'https://github.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
    ],
    'data': [
        # Security
        'security/it_asset_security.xml',
        'security/ir.model.access.csv',

        # Master & Sequence Data
        'data/ir_sequence_data.xml',
        'data/it_asset_stage_data.xml',
        'data/it_asset_location_data.xml',

        # Reports
        'report/it_asset_reports.xml',
        'report/it_asset_issue_report_template.xml',
        'report/it_asset_return_report_template.xml',

        # Views
        'views/it_asset_stage_views.xml',
        'views/it_asset_location_views.xml',
        'views/it_asset_views.xml',
        'views/it_asset_assign_views.xml',
        'views/it_asset_return_views.xml',
        'views/it_asset_disposal_views.xml',
        'views/it_credential_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
