# EH Board: plan to win repeatable dashboard workflows

Prepared 22 September 2026. This plan supersedes the earlier release-planning draft. It distinguishes implemented scope, release verification and future work. The comparison baseline is the supplied NexGen 19.0.1.0.5 package; competitor findings came from static inspection, not a live matched benchmark.

## Decision

Win the complete path from a question to correct figures, an understandable calculation and a reusable result. A larger chart menu alone will not establish that advantage. Release 7.1, now pushed to branches 16.0–20.0, combines the three most material creation gaps: broader AI authoring, guided comparisons of two models and reusable KPI hierarchies. These were previously spread across later proposed releases; they are now one implementation scope for Odoo 16–20.

The honest competitive position remains specific. EH Board has evidence for defined business metrics, selected-view exports, permission isolation, recipient-specific digests, explicit snapshot freshness and native tests across five Odoo majors. NexGen's inspected package remains broader in specialist visualizations, visual SQL/external databases and some advanced hierarchy/data-mart workflows. Neither feature counts nor download counts establish customer preference, speed or calculation correctness.

## Current release: 7.1

| Workflow | Implemented behavior | Acceptance condition |
|---|---|---|
| Create from a business question | Optional AI uses selected readable models, owned snapshots and compatible saved comparisons, in addition to the ten business definitions | Real data preview and selected apply work; permission/company/source changes invalidate old plans; no executable AI SQL, Python or arbitrary domains |
| Compare two datasets | Two sides have explicit models, matching keys, aggregates, filters and date ranges; optional arithmetic; real preview; fixed saved definition | One-to-many test counts parent orders once; monetary units and company scope validated; zero divisor and unmatched keys visible; stale preview cannot save |
| Track objectives | Owned KPI tree, explicit periods, baseline/target/range, positive weights and weighted normalized scores | Correct higher/lower/range math; missing, restricted or stale child blocks parent; no implicit addition of amounts/currencies; atomic preview/save and concurrent-edit rejection |
| Reuse work | Scorecards and guided comparisons participate in templates and portable JSON | New widget references and importer ownership are resolved deliberately; database-local IDs never silently select unrelated records; invalid references fail atomically |
| Maintain version coverage | Same functional scope on 16.0–20.0 with native UI/access adaptations | Native tests, frontend flows, translation validation and distributable archives pass on every branch |

Current boundaries are deliberate and visible. Generic AI excludes monetary fields without a trusted currency definition; untyped snapshots provide counts and breakdowns. A guided comparison handles two independently grouped models, not unrestricted multi-table visual SQL. It caps each side at 1,000 groups and display at 100. Its fixed date scope is not silently rewritten by a dashboard date filter. Scorecards support 60 nodes and five levels; formula-first widgets remain ineligible while undefined arithmetic can appear as zero in the existing formula engine. These boundaries must appear in product documentation and demos.

## First follow-through: prove the shipped workflows

Production target and usable account connections are still required for deployment-specific validation. Local discovery found an older EH Board copy on a configured addon path; selecting the correct loaded path is part of rollout. Do not assume that pushing branches changes the running installation.

Upgrade-and-restore rehearsals already passed on synthetic native Odoo 16, 17, 18, 19 and 20 databases from the previous 6.1 line to 7.0. A separate Odoo19 rehearsal from the discovered 3.0 copy to 7.0 also preserved its sentinel dashboard, source/measure references, values, ownership, custom template and filestore attachment, then restored the old version successfully. These are local synthetic checks, not a rehearsal of a customer backup.

Next rollout steps:

1. Identify the host, database, exact addon directory and operator account. Capture installed module version and backup/restore procedure.
2. Restore a representative database and filestore into staging. Upgrade the matching 7.1 package; check existing dashboards, custom models, sharing, digests and imports.
3. Validate one permitted AI proposal, one representative Sheets source and one approved HTTPS API source using existing connections. Use the supplied live-validation harness for bounded checks and sanitized evidence; provider requests can incur charges even when database changes are rolled back.
4. Let a business owner verify calculation definitions and expected numbers. Include denied-access and stale-data cases, not only administrator success.
5. Deploy the verified package, confirm the loaded version and complete the same smoke checks. Retain rollback artifacts and record the release identifier.

Required input remains host/database and existing connection names or configuration paths. Secret values should not be pasted into the task.

## Competitive proof study

Run both products on equivalent staging copies, identical companies, permissions and fixture data. Use the supplied competitor version and the final EH Board release; record versions and settings. Do not present static-code inferences as measured product outcomes.

| Task | Correct outcome | Proposed win criterion |
|---|---|---|
| Build a sales dashboard | Agreed booked-sales definition, company/currency basis and date range | At least 8 of 10 representative users complete without developer help; median completion time at least 30% below competitor |
| Compare orders and order lines | Parent totals are not duplicated by child count | Exact agreement with independently checked expected totals; understandable join definition |
| Create a dashboard from a custom model using AI | Valid requested widgets from permitted fields only | Successful completion and correct figures in at least 18 of 20 prewritten prompts; unsupported questions explicitly identified |
| Explain a KPI hierarchy | Explicit owner, target period, units and rollup policy | Users can explain a parent score from child scores; inaccessible child never becomes a reassuring zero |
| Export a filtered/drilled analysis | Report matches every selected widget, including deferred widgets | Exact data agreement across UI, CSV/XLSX and PDF report inputs |
| Share and refresh external data | Audience receives only deliberately shared snapshot; stale/error state visible | Zero unauthorized record or credential disclosure; failed refresh retains known data and visible diagnostic |

The proposed time and completion thresholds are targets, not measured results. Use task order randomization, a short equal training session and a written answer key. Report failures and assisted completions. Keep user count, dataset sizes, hardware, warm/cold runs and confidence limits with results. Release-level automated tests support reliability claims; they do not substitute for this usability study.

Performance reference cases should include a 12-widget dashboard, a high-cardinality two-model comparison, a 60-node scorecard and a 10,000-row remote snapshot. Measure p50/p95 response time and query count under a stated concurrent-user load. Initial working target: p95 under two seconds for an individual supported aggregate on the reference dataset, under five seconds for first useful dashboard content, with explicit failure at configured query limits. Adjust thresholds only from recorded workload evidence.

## Next scope after 7.1, in priority order

| Priority | Scope | Why it can win | Completion evidence |
|---|---|---|---|
| P0 | Resolve pilot defects, confirm deployment and provider operation, publish reproducible workflow results | Converts implemented features into credible customer proof | Passed customer-backup rehearsal; named business sign-off; sanitized provider checks; matched workflow report |
| P1 | Stronger financial definitions: agreed FX basis, installment ageing and period-aware financial measures | More useful business questions with less interpretation risk | Finance-approved fixtures covering credits, partial payments, rates, overdue boundaries and multi-company cases; definition visible in every output |
| P1 | Better query reuse: reopen/fork a saved comparison, named reusable calculations, unit-aware formula results | Reduces repeated setup and makes changes reviewable | Versioned definitions; dependent-widget impact preview; no silent mutation of existing analyses; complete migration/permission tests |
| P1 | Formula semantics that distinguish undefined from zero | Enables reliable formula KPIs, ratios, alerts and scorecards | Null/error semantics preserved from calculation through chart, export, alert and score; no false target achievement on zero division |
| P2 | Connector operations and requested external database connectors | Closes a remaining breadth advantage with manageable operation | Read-only service roles, bounded queries, connection tests, credential rotation, clear audience/freshness state and representative live integration tests |
| P2 | Additional chart types driven by real questions | Adds useful visual coverage without inflating a menu | Prioritize three requested views; accessible data fallback, export parity and large/small dataset checks for each |
| P2 | KPI history, approval and effective-date versioning | Makes scorecards usable for recurring management reviews | Historical targets/definitions immutable; owner changes traceable; current snapshots never presented as historical actuals |
| P3 | Authenticated external publishing | Supports a demonstrated client/partner reporting workflow | Named audience, revocation, expiry, audit trail and explicit snapshot scope; no anonymous publication by default |

Keep each scope bounded. External database breadth, historical accounting and externally published dashboards are separate delivery decisions with concrete use cases. Do not promise them as current capabilities.

## Delivery discipline

Keep version parity as a release condition. Port only this module's changes, preserve native-major differences and unrelated branch changes, and package from recorded tested commits. Each release includes setup guidance, translated user messages, meaningful access/semantic/browser checks, a short change report and a clear list of unverified live conditions.

The next competitive claim should name the workflow and evidence: for example, “Users built this tested sales dashboard 30% faster with exact export agreement.” Until a study establishes that result, use the narrower statement that the release closes specified creation gaps and has passed its documented native checks.

## Release references

- [7.1 release scope, tested commits, checksums and validation](RELEASE_7_1_VALIDATION.md)
- [7.1 user guide and supported behavior](RELEASE_7_1.md)

The release record identifies the implementation commits and archives used for the completed native checks. Detailed local logs and deployment-specific material accompany the release artifacts. Production target selection, customer-backup rehearsal and live provider validation remain outstanding.
