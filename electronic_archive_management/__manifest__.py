# -*- coding: utf-8 -*-
{
    'name': 'Electronic Archiving & Document Management',
    'version': '18.0.1.0.0',
    'category': 'Document Management/Archiving',
    'summary': 'Unified Electronic Archiving, Cross-Document Linking & Multi-Tier Search for Odoo',
    'description': """
Electronic Archiving & Document Management System
=================================================
A comprehensive enterprise electronic archiving module designed for Tile & Block sector
(Al-Mudayfer Sons Holding Co) to unify document lifecycles across Inventory, Sales, and Accounting.

Key Features:
-------------
* **Cross-Document Attachment Flow**: Automatically links and displays warehouse delivery/receipt
  attachments on Customer Invoices and Vendor Bills dynamically and retroactively.
* **Centralized Multi-Tier Search Dashboard**: 4-level cascading search (Company -> Fiscal Year -> Application -> Sub-App)
  plus refined filters (Document No, Date range, Document Type, Customer/Vendor, Full-Text).
* **Document Immutability & Audit Security**: Restricts attachment deletion on confirmed/posted transactions
  to ensure strict internal audit trails and compliance.
* **Standard Document Classification**: Pre-configured document taxonomy (Scale slips, Signed delivery notes,
  Customer POs, Bank transfer receipts, Inventory adjustment minutes).
    """,
    'author': 'Horizonz / Al-Mudayfer Sons Holding Co',
    'website': 'https://horizonz.cloud',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'stock',
        'sale_management',
        'account',
    ],
    'data': [
        'security/electronic_archive_security.xml',
        'security/ir.model.access.csv',
        'data/archive_document_type_data.xml',
        'views/archive_document_type_views.xml',
        'views/ir_attachment_views.xml',
        'views/account_move_views.xml',
        'views/stock_picking_views.xml',
        'views/account_payment_views.xml',
        'views/sale_order_views.xml',
        'views/archive_search_views.xml',
        'views/archive_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
