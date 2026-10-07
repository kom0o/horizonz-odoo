# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
# All implementation work is original. The dashboard engine, chart
# rendering, layout engine and data pipeline are built from the ground
# up in OWL and Python. No layout, naming, markup, or template derives
# from any proprietary or third-party Odoo dashboard module.
#
##############################################################################
{
    "name": "Dashboard Builder",
    "summary": "Business dashboards for Odoo 18 Community: preview Sales, Receivables and "
               "Warehouse packs, trace metric definitions, create charts with optional AI, "
               "and export the selected analysis. Includes 26 chart and widget types, "
               "pivot, map, filters, drill-down, targets, snapshots and alerts.",
    "description": """Dashboard Builder helps teams create useful Odoo dashboards and understand the figures behind them.

Start with a business pack, preview your accessible data, read each metric definition and create a private draft. Customize the result with the visual builder or request a supported dashboard from the optional AI authoring assistant.

Business packs:

- Sales performance: confirmed untaxed order value, average order value and order counts. Fixed to one company and orders in its currency; foreign-currency orders are excluded. These are booked sales, not accounting revenue.
- Cash and receivables: current signed customer residuals and overdue document balances in company currency, including credit notes. These are current balances, not historical as-of balances, installment ageing or cash forecasts.
- Warehouse operations: current open and late transfers, plus completed transfers by completion period. Counts transfer documents, including returns, not units or inventory value.

AI and guided creation:

- Smart Build remains deterministic and works without an AI key.
- Optional OpenAI or Anthropic authoring proposes charts from a versioned, permitted metric catalogue. Review the plan and real-data preview before applying it. Unsupported definitions are identified; the assistant cannot execute arbitrary SQL or Python.
- Optional AI narration summarizes already-computed facts. Authoring sends your prompt and permitted metric descriptions; narration sends computed facts. Raw record rows, SQL and stored credentials are excluded from these content payloads. The configured provider receives its authentication key, and its usage charges apply.

Dashboard tools:

- 26 registered chart and widget types, including KPI, pivot, map, tables, slicers and content. Original SVG charts load without a chart CDN.
- Readable Odoo models with ORM access rules, two-model grouped joins, CSV/XLSX upload, arithmetic measures, targets and period comparisons.
- Administrator-configured Google Sheets and HTTPS JSON sources with scheduled refresh, cached snapshots and visible freshness. Private Sheets can use a service account; REST sources support flat rows and numbered pagination. Source owners explicitly authorize the dashboard audience to view the imported snapshot.
- Administrator-only SQL on the current Odoo database, guarded by statement checks, timeout and rollback. Raw SQL does not inherit Odoo record rules; configure a least-privilege database role for additional protection.
- Drag, resize, layout history, mobile stacking, dark/light themes, cross-filtering, date filters and multi-level drill.
- Current-view insights and exports, native XLSX, CSV, per-chart PNG, portable JSON definitions, browser vector printing and server PDF documents. Saved digest context is separate from the interactive view.
- Internal user/group sharing, snapshot history, re-arming threshold alerts, scheduled PDF digests and presentation mode. Automatic refresh uses polling.
- Keyboard and screen-reader data access, right-to-left layouts and locale catalogs.

Performance depends on model size, grouping, permissions and database configuration. Grouped ORM reads and bounded loading reduce work; no fixed response time is promised. Remote sources refresh on a schedule rather than on each chart request. The core does not include external-database connectors, anonymous chart publishing or historical receivables reconstruction.
""",
    "author": "ERP Heritage",
    "website": "https://www.erpheritage.com.au/",
    "license": "OPL-1",
    "price": 0.0,
    "currency": "EUR",
    "category": "Productivity/Dashboard",
    "version": "18.0.7.1.0",
    "application": True,
    "installable": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/eh_board_groups.xml",
        "security/ir.model.access.csv",
        "security/eh_isolation_rules.xml",
        "security/eh_board_scorecard_security.xml",
        "views/eh_board_datasource_views.xml",
        "views/eh_board_remote_views.xml",
        "views/eh_board_item_views.xml",
        "views/eh_board_dashboard_views.xml",
        "views/eh_board_menus.xml",
        "views/eh_board_alert_views.xml",
        "views/eh_board_credential_views.xml",
        "views/res_config_settings_views.xml",
        "report/eh_board_report_templates.xml",
        "report/eh_board_reports.xml",
        "data/eh_board_crons.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "eh_board/static/src/**/*",
        ],
        "web.assets_tests": [
            "eh_board/static/tests/**/*",
        ],
    },
    "images": [
        "static/description/banner.gif",
        "static/description/shot_hero.png",
        "static/description/shot_gallery.png",
        "static/description/shot_map.png",
        "static/description/shot_builder.png",
        "static/description/shot_combo.png",
        "static/description/shot_pivot.png",
        "static/description/shot_present.png",
    ],
}
