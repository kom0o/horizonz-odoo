# Dashboard Builder 7.0

## Changes

- Three business packs use versioned metric definitions: Sales performance, Cash and receivables, and Warehouse operations. Preview real accessible data before creating a private draft. Existing saved dashboards and user templates are preserved.
- Business widgets show how values are calculated. Their calculation, company, source and date basis remain attached to their definition. Detach a definition before changing those properties; ordinary presentation changes remain available.
- Optional AI authoring proposes a bounded dashboard plan from permitted metrics. Review definitions, unsupported requests and real-data previews, then apply selected widgets. Refinement edits the proposal before applying it. Smart Build remains a separate deterministic tool that needs no provider key.
- Insights, CSV, native XLSX and server PDF use an explicit analysis context. Exports fetch the requested widgets, including deferred cards. Browser printing and server PDF remain different formats: server documents contain formatted data, while browser printing preserves chart vectors.
- Administrator-configured Sheets and HTTPS JSON sources refresh into cached snapshots. Dashboards show freshness and last successful refresh. Failed refreshes retain previous valid rows with a stale status; demo rows are not substituted.

## Upgrade

1. Back up the database and installed module directory. Use the package matching the Odoo major version.
2. Replace the module files and upgrade `eh_board` through the normal Odoo deployment process. Restart all workers and refresh browser assets.
3. Check that existing dashboards, sources, templates and user access remain correct. New versioned packs are added without rewriting existing boards.
4. Verify the new flows on representative company data before expanding access. Review optional Python dependencies below.

Release test results belong to the accompanying release artifacts. This guide does not claim validation against every Enterprise combination or customer database.

## Create a business dashboard

Open the dashboard gallery, choose a business area and select **Preview my data**. The preview uses the current company and your access rights. No preview board is retained. Read **How calculated**, then create the private draft. Saved templates and earlier starters remain available below the business packs.

| Pack | Meaning and limits |
|---|---|
| Sales performance | Confirmed orders only; untaxed values and order counts use orders in the current company's currency. Foreign-currency orders are explicitly excluded. This is booked sales, not accounting revenue. Order date controls period filtering. |
| Cash and receivables | Current signed residuals of posted customer invoices and credit notes, in company currency. Credit notes reduce net balances. Overdue uses document due date, not installment-level ageing. Current balance widgets ignore period filters; they do not reconstruct historical as-of balances or forecast cash. |
| Warehouse operations | Current open and late transfers, including returns, plus completed transfers by completion period. Counts documents, not units, net deliveries or inventory value. Current backlog widgets ignore period filters. |

Each pack requires its matching app and readable metric fields. Missing access or unavailable definitions block creation rather than silently replacing metrics. Empty permitted datasets can legitimately show zero or no rows.

To customize a calculation, detach the business definition. Detachment removes definition metadata. For overdue and late metrics, the current relative cutoff becomes a fixed ordinary filter; review that filter before saving the custom widget. Importing a definition-backed template retains its metric version and binds it to the importing user's current company.

## Optional AI

An administrator stores the provider key under Dashboard Configuration credentials, then selects OpenAI or Anthropic, a compatible model, an optional base URL and the credential name in Dashboard AI settings. Authoring and narration use the same configured provider. The configured endpoint must respond directly; redirects are not followed.

Authoring sends your prompt, permitted metric definitions and any proposal being refined. Narration sends computed dashboard facts. Raw record rows, SQL and stored credentials are excluded from those content payloads. The provider receives its authentication key. Do not put secrets into a prompt. Provider billing and retention settings belong to your provider account.

Authoring is limited to supported metric definitions, breakdowns, periods and charts. It cannot author arbitrary SQL or Python. Unsupported requests must be revised or completed through the normal advanced builder. Generation never applies changes automatically. Without a provider, deterministic suggestions and Smart Build remain available.

Administrators can set system parameters `eh_board.ai_authoring_daily_requests` and `eh_board.ai_authoring_max_tokens`. Defaults are 20 authoring requests per user per UTC day and 1,800 output tokens per generation. These are request/output limits, not a currency-denominated billing guarantee. Narration has separate bounded input/output handling.

## Google Sheets

1. Enable the Google Sheets API in the Google Cloud project used by your service account.
2. Share the spreadsheet with the service account's `client_email` as Viewer. The connector does not request domain-wide delegation.
3. Store the service-account JSON as a dashboard credential. Install the optional `google-auth` Python package on the Odoo server for this authentication mode.
4. As Dashboard Administrator, configure the source with the spreadsheet ID and a finite A1 range that includes its header row, such as `Sheet1!A1:F1001`.
5. Confirm that the dashboard audience may view the imported snapshot, refresh and inspect the columns/data. Configure the refresh interval.

An expiring OAuth bearer token can be supplied instead, with manual token renewal and an explicit expiry. This release does not include a browser OAuth consent flow. Use a narrow finite range; unbounded spreadsheet ranges are not accepted.

## HTTPS JSON sources

Configure a public HTTPS endpoint on port 443 that returns a flat array of objects. Select the row location using a JSON pointer, for example `/data/items`. GET is supported. Authentication may be absent, bearer, basic or an `X-` API-key header, using server-side credentials.

Numbered pagination starts at page 1 and uses configurable page and page-size query parameters. It stops at a short page and permits at most ten pages. Arbitrary cursors and nested-object flattening are not supported.

Remote input is bounded to 8 MB, 10,000 rows and 60 columns. Redirects and private network destinations are rejected. Refresh intervals range from five minutes to seven days, with retry backoff. A failed refresh or incompatible schema keeps the prior valid snapshot and displays its age and error state. Rendering reads the cache rather than waiting for the remote service.

Remote configuration, refresh and raw preview require Dashboard Administrator access. Imported rows are shared with the authorized dashboard audience as a snapshot. Odoo source-model record rules cannot filter an external spreadsheet or API dataset on each viewer's behalf; choose the audience accordingly. Credentials and live remote data are excluded from portable dashboard definitions. Imported remote sources require administrator reconnection.

## SQL, files and performance

The SQL provider addresses the current Odoo database. It is restricted to privileged administrators and applies statement checks, row bounds, a timeout and rollback. Raw SQL does not inherit ORM record rules. A dedicated least-privilege database role provides additional protection. External PostgreSQL/MySQL/MSSQL connections are not included.

CSV/XLSX sources remain manual uploads. XLSX parsing needs `openpyxl`; native workbook export needs `xlsxwriter`. Server PDF generation uses the deployment's supported Odoo PDF facilities. Chart PNG applies to SVG charts; HTML widgets use their data export or print flow.

Automatic and “live” refresh use polling. Source freshness depends on its scheduled refresh. Database grouping and bounded loading limit work, but latency still depends on model size, grouping, access rules, concurrency and deployment resources. Benchmark your workload rather than relying on a universal million-row claim.
