# -*- coding: utf-8 -*-
{
    'name': 'Horizonz Tiles & Concrete Manufacturing',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing/Manufacturing',
    'summary': 'Comprehensive Tiles, Interlock, Concrete Blocks & Terrazzo Manufacturing Management',
    'description': """
Horizonz Tiles & Concrete Manufacturing Management
===================================================
A specialized Odoo 18 manufacturing extension designed for tile, interlock,
concrete blocks, and terrazzo manufacturing facilities.

Key Features:
-------------
* **Production Halls & Line Hierarchy**: Full mapping of production hangers, multi-stage lines (OCEM, MASA, HERANDO).
* **Engineering Product Attributes**: Tile dimensions, colors, units per m², truck & crane loading capacities.
* **Standard Capacity Norms**: Mould cavities, speed standards for press & grinder, steam curing hours, standard waste %.
* **Unified Shift Production Sheets (ورقة الوردية)**: Daily coordination of pressing, grinding, quality grading, and breakdowns.
* **Quality & Grading Matrix**: Automatic multi-tier sorting (Grade 1, Grade 2, Skirting, Regrind, Scrap/Waste).
* **Breakdown & Stoppage Tracking**: 187 pre-configured causes mapped to machine components with OEE loss analysis and Maintenance ticket creation.
* **Printable Shift Reports**: Official PDF reports ready for shift sign-offs.
    """,
    'author': 'Horizonz',
    'website': 'https://horizonz.cloud',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mrp',
        'stock',
        'product',
        'maintenance',
        'resource',
    ],
    'data': [
        'security/mrp_tile_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mrp_tile_group_data.xml',
        'data/mrp_hanger_data.xml',
        'data/mrp_breakdown_cause_data.xml',
        'views/mrp_tile_group_views.xml',
        'views/mrp_production_hanger_views.xml',
        'views/mrp_workcenter_views.xml',
        'views/product_template_views.xml',
        'views/mrp_line_capacity_views.xml',
        'views/mrp_breakdown_cause_views.xml',
        'views/mrp_shift_log_views.xml',
        'views/mrp_tile_menus.xml',
        'reports/mrp_shift_log_report.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
