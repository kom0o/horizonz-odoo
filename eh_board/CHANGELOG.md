# Dashboard Builder

## 6.1.0 — 2026-09-22 (Odoo 16–20)

- Horizontal bar charts display complete category names in a responsive label area. Long names wrap, dense charts scroll vertically, and wider widgets allow fewer line breaks. SVG text, drill targets and right-to-left layouts remain intact.
- Export very tall charts as a complete PNG, scaling dimensions within browser canvas limits. Ordinary charts retain their existing export resolution.
- Slicers automatically use a compact scrollable list above ten values. The widget builder offers Automatic, Compact list and Chips. Search, multiple selection, Clear and keyboard navigation remain available; the setting survives edits and portable exports.
- Refresh every translation catalog from the current source of each Odoo version. Complete all nineteen languages and add the supplied Spanish (Argentina) catalog. Preserve its current-source translations except a correction to literal tokens in a JSON example.
- Translate previously hardcoded builder controls, date presets, messages, dynamic buttons, tooltips and chart legends. Format translated placeholders correctly on Odoo 16.
- Retain the released app-level overlay fix for the export menu and its browser regression coverage.
- Add catalog completeness and source-freshness checks, strict placeholder/markup validation, focused chart/slicer tests, and a browser regression covering thirty long category names and thirty slicer choices.

Upgrade the module and restart Odoo workers so Python and JavaScript code translations are reloaded from disk. Regenerate browser assets or refresh the browser after the upgrade. The release includes complete translation files; importing a PO through Settings alone does not replace the module code catalogs.
