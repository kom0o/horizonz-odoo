# Dashboard Builder 7.1: create, compare and score

This release adds broader AI proposals, guided comparisons of two models, and reusable KPI scorecards. All three tools use the dashboard's access controls. AI is optional; comparison and scorecard tools work without an AI provider.

## Build with AI from selected data

Open **Build with AI**. Existing Sales, Receivables and Warehouse definitions remain available. Add up to three readable Odoo models or sources owned by the current dashboard. The permitted catalogue then includes bounded record counts, non-monetary numeric measures, category/date breakdowns and compatible saved comparisons.

The catalogue is generated on the server from the selected data and current permissions. AI cannot submit SQL, Python, arbitrary domains, new field names or its own metric definitions. Every preview and apply rebuilds the permitted catalogue. Changes to data selection, company, access or source configuration invalidate old proposals. Review the real-data preview and select the widgets to add. Preview does not persist widgets.

Generic model measures exclude monetary fields because a field name alone cannot prove a safe currency basis. Use the defined financial metrics for supported monetary questions. File, Sheets and API snapshots offer counts and breakdowns; untyped numeric columns are not promoted into financial measures. Data selection sends permitted metadata and the prompt to the configured provider, not raw record rows. Provider charges still apply.

## Compare two models

Open **Menu → Compare two models**. Choose a company, then a readable model, matching key and aggregate on each side. Add typed filters and optional date ranges separately. Matching keys must share a compatible scalar type or refer to the same related model. This is a comparison of two independently grouped datasets: one-to-many row expansion does not duplicate the parent aggregate.

Choose all keys from either side, every left key, or only keys present on both sides. Unassigned keys never match one another. Missing sides contribute zero and are identified in the preview. Optional arithmetic uses `a` for the left aggregate and `b` for the right. Undefined division is displayed as zero with an explicit warning; it must not be interpreted as a measured zero ratio.

Preview shows the actual grouped values, calculation, scope, units and warnings. Changing settings requires a fresh preview before Save. Saving creates one board-owned source and one widget. The saved calculation is fixed; create another comparison to change its definition. Saved date scopes remain independent of the dashboard date selector, and an incompatible interactive scope is rejected instead of silently changing the calculation.

Each side is limited to 1,000 groups; displayed results are limited to 100. Exceeding the side limit fails explicitly instead of returning a partial comparison. Monetary aggregates must meet the selected-company currency rules; no FX conversion is performed. Both sides are queried under the reader's current access rights.

## KPI scorecards

Open **KPI scorecard**. Editors create weighted objectives and attach metric widgets from the same dashboard. Each node has an owner, an explicit effective period and a positive relative weight. Enter a baseline and target deliberately, including zero where intended; the tool supplies no business target.

Scoring supports higher-is-better, lower-is-better and a target range. Scores are capped between 0 and 100. Groups average child scores using their relative weights. They never add business amounts, currencies or averages. **How calculated** shows the formula and metric definition.

Select the complete target period to evaluate it. Current balances and snapshots cannot score a historical period. Other active dashboard filters and drill paths remain in force; targets are not automatically rescaled for a filtered audience. Missing, inaccessible or stale values remain unavailable. A blocked child prevents its parent from receiving a misleading complete score.

Formula-first widgets are currently ineligible because the existing formula engine can represent undefined arithmetic as zero. SQL and legacy joined sources require a supported scalar widget. The scorecard supports up to 60 nodes and five levels. Preview is temporary; Save applies the whole tree atomically and rejects a conflicting edit from another session.

## Reuse and portability

Saved templates and JSON backups include scorecard definitions, explicit targets and periods. Widget references are remapped to the newly created widgets. Owners become the importing user; review ownership and target suitability before publishing the imported private draft. Missing referenced widgets cause the import to fail instead of linking a target to an unrelated metric.

Portable guided comparisons use technical model names and the importing user's current company. Filters containing database-specific record IDs cannot be exported as portable comparisons. Replace such filters with names, states or dates, or recreate the comparison deliberately in the destination database. Imported definitions are validated again against destination models, fields and access rights. Credentials, cached remote rows and SQL query text remain excluded from portable backups.

## Installation and validation

Upgrade the module in the matching Odoo major branch. Existing dashboards, layouts and sources remain available. No live provider call is needed for deterministic comparisons or scorecards. For a production upgrade, confirm the actual loaded addon path and database, take a database and filestore backup, then rehearse the upgrade on a restored copy before rollout.

Release evidence distinguishes native automated checks, synthetic upgrade rehearsals and live production/provider validation. Passing the first two does not establish the third. See the release package's validation report for the tested commit, major versions and remaining limitations.
