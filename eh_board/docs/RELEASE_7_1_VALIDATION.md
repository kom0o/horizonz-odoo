# EH Board 7.1 release scope and validation

Release date: 22 September 2026. This record accompanies the implementation already published on Odoo branches 16.0 through 20.0. It documents the tested code and original release archives; adding this record does not change product behavior or regenerate those archives.

## What changed

### Broader AI authoring

The existing ten business definitions now support an optional data scope of up to three readable Odoo models or dashboard-owned sources. The server builds a bounded catalogue of counts, non-monetary numeric aggregates, dimensions, date choices and compatible saved comparisons. Real-data preview precedes selected, atomic application. Company, permission or source changes invalidate affected proposals, and changing the selected scope clears the old proposal in the dialog.

AI output cannot supply executable SQL, Python, arbitrary domains or invented metric definitions. The generic route excludes monetary fields without a trusted currency basis. Untyped remote snapshots offer counts and breakdowns. Provider requests receive permitted metadata and the prompt, not raw business rows; saved-comparison filter literals are excluded.

### Guided comparisons of two models

Each side defines a model, matching key, aggregate, typed filters and optional dates. Independent aggregation prevents one-to-many matches from multiplying parent totals. Full, left and inner matching expose unmatched keys; optional arithmetic combines the two aggregate values. A successful preview is required before saving one fixed source definition and one widget.

The workflow validates compatible keys, company/currency basis, current reader permissions and bounded group counts. Each side supports at most 1,000 groups and the output at most 100 displayed results. Missing sides contribute zero and remain identified; undefined division returns zero with an explicit warning. This is a two-model aggregate workflow, not unrestricted visual SQL or FX conversion. Saved date scope remains explicit rather than being silently rewritten by dashboard date controls.

### Weighted KPI scorecards

Editors build trees of objectives and metric widgets with explicit owners, effective periods, baselines, targets and positive weights. Higher-is-better, lower-is-better and range scoring normalize results to 0–100. Parents combine weighted child scores, never mixed business amounts or currencies.

Missing, restricted or stale children block a complete parent result. Current balances and snapshots do not establish historical actuals. Formula-first widgets remain ineligible while the legacy calculation path can represent undefined arithmetic as zero. Trees support up to 60 nodes and five levels. Preview is temporary; atomic saves reject conflicting edits.

### Portability and ordinary-builder permissions

Templates and portable JSON preserve scorecards and compatible guided comparisons. Imports remap widget references, assign ownership to the importer, rebind the current company deliberately and revalidate destination models and fields. Database-local record-ID filters cannot silently select unrelated destination records. Invalid references fail atomically.

Builder, filter, drill, list, export and template paths resolve registry metadata without requiring Settings administration, while retaining the caller's business-model and field permissions. Odoo20 also retains its native fresh field-access checks. Regression coverage includes ordinary-builder round trips and denied-field export/import cases.

### Native version coverage and localization

Each branch retains its native Odoo access, view and frontend adaptations. All 20 locale catalogues were refreshed from native exports, checked for completeness and format correctness, and validated after loading into the corresponding native runtime.

## Tested implementation commits

The following counts come from the final full suites. Focused runs overlap those suites and add no unique tests. Translation counts are verified Python/browser entries across 20 locales per version, not counts of distinct source messages or linguistic certification.

| Odoo | Module version | Tested implementation commit | Native tests passed | Runtime translation checks |
| --- | --- | --- | ---: | ---: |
| 16.0 | 16.0.7.1.0 | `7958b03b0c9ee8a1f0874a6396dcaead7568a0b5` | 285 | 24,940 |
| 17.0 | 17.0.7.1.0 | `671ae395aa92346a67942bfda8bb9a3b03d4c002` | 285 | 25,060 |
| 18.0 | 18.0.7.1.0 | `7e73e65ebf3e0ed5416a93aa2998f000caeded2c` | 285 | 25,060 |
| 19.0 | 19.0.7.1.0 | `a66891786a3228a97bcc3e99e7a5abb464ff5ec2` | 285 | 25,160 |
| 20.0 | 20.0.7.1.0 | `d3af0b379f4681740a37843f2996b9eb3f3d02ab` | 314 | 25,180 |

**Total: 1,454 native tests, zero failures/errors, and 125,400 runtime translation checks.**

The native suites include backend access/calculation checks and real browser flows for authoring, comparison, scorecard preview/save and existing dashboard behavior. Each version includes ten portability tests. Supporting checks cover chart labels, slicers, PNG utilities, translation-gate tests, all 100 locale/version catalogues, gettext format validation and whitespace. No remote CI outcome is claimed.

## Original release archives

The original archives were generated directly from the implementation commits above. Verification covered ZIP integrity, embedded Git commit, bundled module version, expected feature files, all 20 locale files and SHA-256 readback. These checksums continue to identify those archives after documentation-only follow-up commits.

| Archive | SHA-256 |
| --- | --- |
| `eh_board-16.0.7.1.0.zip` | `734b97d2a3ee6107ccbc46d0edab2393707e24500a17dc64d133fa605ee36279` |
| `eh_board-17.0.7.1.0.zip` | `bf2bd5ed7013e5741109b712ec48ba4f45cc38879545fc96018f641908f01bce` |
| `eh_board-18.0.7.1.0.zip` | `96f7499a21f57754bcd7ca8937062d3d0ea8cc70d5771ba15b1f40e2b3efe8da` |
| `eh_board-19.0.7.1.0.zip` | `db4433d9df0f5e5219287b4adb167fa3b3ac36b2c0528231848f05ed4721a75a` |
| `eh_board-20.0.7.1.0.zip` | `c55537a8d8b8a2311a7502e6d003a8ad7380aeb7205236fd617b3ba9e488cd44` |

## Validation boundaries

Native checks used Community runtimes and synthetic local databases. AI and remote-provider test transports used controlled responses. No live AI, Sheets or REST-provider operation, customer production installation, customer-backup rehearsal or matched competitor usability/performance benchmark is established by these results. Earlier synthetic upgrade/restore rehearsals to 7.0 remain separate background evidence.

The supplied NexGen 19.0.1.0.5 package was inspected statically. This release closes specific authoring, comparison and KPI-hierarchy gaps; it does not establish overall superiority or parity with advanced visual SQL, external database connectors, data marts or specialist chart breadth.

## Next scope

The [next scope plan](NEXT_SCOPE_PLAN.md) defines priorities and acceptance criteria:

1. Validate a named staging/production target, existing provider connections and representative customer data; run a matched six-workflow competitive study.
2. Deepen financial definitions with explicit FX basis, installment ageing and period-aware measures.
3. Add reusable, versioned comparisons and calculations, including dependency-impact review.
4. Distinguish undefined arithmetic from measured zero throughout charts, exports, alerts and scorecards.
5. Expand connectors and chart types from demonstrated demand; add KPI history and approval before authenticated external publishing.

Proposed completion-time, AI-success and performance thresholds in the plan are targets, not measured wins. See the [user guide](RELEASE_7_1.md) for current operation and limits.
