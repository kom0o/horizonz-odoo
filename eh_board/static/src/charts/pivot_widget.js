/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Pivot / cross-tab matrix widget. Renders measures against row and column
 * dimensions with row/column subtotals and a grand total. All shaping is done
 * server-side; this component only lays out a ready matrix into an accessible
 * HTML table (real <table>, sticky header + first column, optional heat map,
 * click-through drill on any cell). No canvas, no external grid lib. */

import { Component, useState, onWillUpdateProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { formatValue } from "./svg_util";
import { matchRule, textOn } from "../conditional";
import { percentColumnLabel } from "../measure_label";

export class PivotWidget extends Component {
    static template = "eh_board.PivotWidget";
    static props = {
        payload: Object,
        meta: { type: Object, optional: true },
        onDrill: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({ page: 1, pageSize: 20 });
        onWillUpdateProps(() => { this.state.page = 1; });
    }

    get p() {
        return this.props.payload || {};
    }
    get measureKeys() {
        return this.p.measure_keys || [];
    }
    get calculations() {
        return this.p.measure_calculations || {};
    }
    get aggregates() {
        return this.p.measure_aggregates || {};
    }
    get displayMeasures() {
        const out = [];
        for (const mk of this.measureKeys) {
            out.push({ mk, calculation: null, label: this._mlabel(mk) });
            const calculation = this.calculations[mk];
            if (calculation && calculation !== "none") {
                out.push({
                    mk, calculation, percentage: true,
                    label: percentColumnLabel(
                        this._mlabel(mk), calculation, this.aggregates[mk]),
                });
            }
        }
        return out;
    }
    get single() {
        return this.displayMeasures.length === 1;
    }
    get hasCol() {
        return !!this.p.has_col && (this.p.col_headers || []).length > 0;
    }
    get heatOn() {
        return !!this.p.heatmap && this.single;
    }
    _mlabel(mk) {
        return (this.p.measure_labels || {})[mk] || mk;
    }
    _fmt(v, mk) {
        const series = (this.p.series || []).find((item) => item.key === mk) || {};
        return formatValue(v || 0, series.number_format || this.p.number_format || "compact",
            series.currency || this.p.currency, series.unit || this.p.unit || "");
    }
    _percent(value, denominator) {
        const n = Number(value) || 0;
        const d = Number(denominator) || 0;
        if (!d) return "0%";
        return `${(n / d * 100).toFixed(1).replace(/\.0$/, "")}%`;
    }
    _skey(k) {
        // Must agree with the Python _skey: null/undefined -> "∅"; booleans map
        // to lower-case "true"/"false" (String(true) already gives "true"), so a
        // boolean row matches its cells instead of rendering an all-zero row.
        if (k === null || k === undefined) return "∅";
        return String(k);
    }
    _cellVal(rks, cks, mk) {
        const row = (this.p.cells || {})[rks] || {};
        const c = row[cks] || {};
        return c[mk] || 0;
    }
    _heatStyle(v, max) {
        if (!this.heatOn || !max) return "";
        // Light -> saturated mint proportional to magnitude; keeps text legible.
        const t = Math.min(1, Math.abs(v) / max);
        const alpha = (0.06 + t * 0.42).toFixed(3);
        return `background: color-mix(in srgb, var(--eh-board-accent) ${Math.round(alpha * 100)}%, transparent);`;
    }
    get rules() {
        return (this.props.meta && this.props.meta.conditional_rules) || [];
    }
    _cellStyle(v, mk, heatMax) {
        // A matching colour rule wins over the heat map; else fall back to heat.
        const cond = matchRule(this.rules, v, this.measureKeys.indexOf(mk));
        if (cond) {
            return cond.style === "fill"
                ? `background:${cond.color};color:${textOn(cond.color)};`
                : `color:${cond.color};font-weight:700;`;
        }
        return this._heatStyle(v, heatMax);
    }

    /** The whole matrix, precomputed into header rows, body rows and a footer
     *  so the template is a plain triple t-foreach with no branching logic. */
    get grid() {
        const p = this.p;
        const mkeys = this.measureKeys;
        const displayMeasures = this.displayMeasures;
        const single = this.single;
        const hasCol = this.hasCol;
        const cols = p.col_headers || [];
        const rows = p.row_headers || [];

        // Leaf body columns: (column value x measure) when there is a column
        // dimension, otherwise one per measure.
        const leaf = [];
        if (hasCol) {
            for (const c of cols) {
                for (const measure of displayMeasures) {
                    leaf.push({ cks: this._skey(c.key), raw: c.key, ...measure });
                }
            }
        } else {
            for (const measure of displayMeasures) {
                leaf.push({ cks: "__m__", raw: null, ...measure });
            }
        }

        // Header rows.
        const headerRows = [];
        const corner = { label: p.row_dim_label || "", corner: true, span: 1 };
        if (hasCol && !single) {
            const r1 = [corner];
            for (const c of cols) r1.push({ label: c.label, span: displayMeasures.length });
            r1.push({ label: _t("Total"), span: displayMeasures.length, total: true });
            const r2 = [{ label: "", corner: true, span: 1 }];
            for (let i = 0; i < cols.length; i++) {
                for (const measure of displayMeasures) {
                    r2.push({ label: measure.label, percentage: measure.percentage });
                }
            }
            for (const measure of displayMeasures) {
                r2.push({ label: measure.label, total: true, percentage: measure.percentage });
            }
            headerRows.push(r1, r2);
        } else if (hasCol && single) {
            const r1 = [corner];
            for (const c of cols) r1.push({ label: c.label });
            r1.push({ label: _t("Total"), total: true });
            headerRows.push(r1);
        } else {
            const r1 = [corner];
            for (const measure of displayMeasures) {
                r1.push({ label: measure.label, percentage: measure.percentage });
            }
            headerRows.push(r1);
        }

        // Heat-map scale (single measure only).
        const maxByM = {};
        if (this.heatOn) {
            for (const mk of mkeys) {
                let mx = 0;
                for (const r of rows) {
                    const rks = this._skey(r.key);
                    const cc = hasCol ? cols : [{ key: "__m__" }];
                    for (const c of cc) {
                        const cks = hasCol ? this._skey(c.key) : "__m__";
                        mx = Math.max(mx, Math.abs(this._cellVal(rks, cks, mk)));
                    }
                }
                maxByM[mk] = mx || 1;
            }
        }

        // Body rows.
        const bodyRows = [];
        for (const r of rows) {
            const rks = this._skey(r.key);
            const cells = [];
            for (const lc of leaf) {
                const v = this._cellVal(rks, lc.cks, lc.mk);
                let text = this._fmt(v, lc.mk);
                if (lc.calculation) {
                    const denominator = lc.calculation === "percent_row"
                        ? ((p.row_totals[rks] || {})[lc.mk] || 0)
                        : lc.calculation === "percent_column" && hasCol
                            ? ((p.col_totals[lc.cks] || {})[lc.mk] || 0)
                            : (p.grand_total[lc.mk] || 0);
                    text = this._percent(v, denominator);
                }
                cells.push({
                    text,
                    style: lc.calculation ? "" : this._cellStyle(v, lc.mk, maxByM[lc.mk]),
                    percentage: !!lc.calculation,
                    drill: true, rowRaw: r.key, colRaw: lc.raw,
                });
            }
            if (hasCol) {
                for (const measure of displayMeasures) {
                    const value = (p.row_totals[rks] || {})[measure.mk] || 0;
                    const denominator = measure.calculation === "percent_row"
                        ? value : (p.grand_total[measure.mk] || 0);
                    cells.push({
                        text: measure.calculation ? this._percent(value, denominator) : this._fmt(value, measure.mk),
                        total: true, percentage: !!measure.calculation,
                    });
                }
            }
            bodyRows.push({ label: r.label, cells });
        }

        // Footer (column totals + grand total).
        const fcells = [];
        if (hasCol) {
            for (const lc of leaf) {
                const value = (p.col_totals[lc.cks] || {})[lc.mk] || 0;
                const denominator = lc.calculation === "percent_column"
                    ? value : (p.grand_total[lc.mk] || 0);
                fcells.push({
                    text: lc.calculation ? this._percent(value, denominator) : this._fmt(value, lc.mk),
                    percentage: !!lc.calculation,
                });
            }
            for (const measure of displayMeasures) {
                const value = p.grand_total[measure.mk] || 0;
                fcells.push({
                    text: measure.calculation ? this._percent(value, value) : this._fmt(value, measure.mk),
                    grand: true, percentage: !!measure.calculation,
                });
            }
        } else {
            for (const measure of displayMeasures) {
                const value = p.grand_total[measure.mk] || 0;
                fcells.push({
                    text: measure.calculation ? this._percent(value, value) : this._fmt(value, measure.mk),
                    grand: true, percentage: !!measure.calculation,
                });
            }
        }
        const footer = { label: _t("Total"), cells: fcells };

        return { headerRows, bodyRows, footer };
    }

    get totalRows() { return (this.p.row_headers || []).length; }
    get totalPages() { return Math.max(1, Math.ceil(this.totalRows / this.state.pageSize)); }
    get page() { return Math.min(this.state.page, this.totalPages); }
    get pagedGrid() {
        const grid = this.grid;
        const start = (this.page - 1) * this.state.pageSize;
        return { ...grid, bodyRows: grid.bodyRows.slice(start, start + this.state.pageSize) };
    }
    get rangeLabel() {
        if (!this.totalRows) return _t("0 rows");
        const start = (this.page - 1) * this.state.pageSize + 1;
        const end = Math.min(this.totalRows, start + this.state.pageSize - 1);
        return `${start}–${end} ${_t("of")} ${this.totalRows}`;
    }
    setPage(delta) {
        this.state.page = Math.max(1, Math.min(this.totalPages, this.page + delta));
    }
    setPageSize(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.pageSize = [10, 20, 50, 100].includes(value) ? value : 20;
        this.state.page = 1;
    }

    onCellClick(row, cell) {
        if (!this.props.onDrill || !cell.drill) return;
        const domain = [];
        const rf = this.p.row_field, cf = this.p.col_field;
        if (rf) this._pushLeaf(domain, rf, this.p.row_field_type, cell.rowRaw);
        if (cf) this._pushLeaf(domain, cf, this.p.col_field_type, cell.colRaw);
        this.props.onDrill({ domain, label: row.label });
    }

    /** Push a domain leaf for a dimension value: a period range for a date/
     *  datetime bucket, an equality otherwise. */
    _pushLeaf(domain, field, ftype, raw) {
        if (raw === null || raw === undefined) {
            domain.push([field, "=", false]);
            return;
        }
        if ((ftype === "date" || ftype === "datetime") && typeof raw === "string") {
            const range = this._periodRange(raw, this.p.granularity);
            if (range) {
                domain.push([field, ">=", range.start], [field, "<", range.end]);
                return;
            }
        }
        domain.push([field, "=", raw]);
    }

    _periodRange(iso, granularity) {
        // Parse the bucket key as LOCAL date/time components (never new Date(iso),
        // which reads a date-only string as UTC and can shift the day), and format
        // the range back the same way - so no toISOString() UTC drift. An hour
        // bucket yields a datetime range; coarser buckets yield a date range.
        const m = String(iso).match(/(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}))?/);
        if (!m) return null;
        const hour = m[4] ? +m[4] : 0;
        const d = new Date(+m[1], +m[2] - 1, +m[3], hour);
        const e = new Date(d);
        switch (granularity) {
            case "hour": e.setHours(e.getHours() + 1); break;
            case "day": e.setDate(e.getDate() + 1); break;
            case "week": e.setDate(e.getDate() + 7); break;
            case "quarter": e.setMonth(e.getMonth() + 3); break;
            case "year": e.setFullYear(e.getFullYear() + 1); break;
            case "month":
            default: e.setMonth(e.getMonth() + 1); break;
        }
        const p = (n) => String(n).padStart(2, "0");
        const fmt = (x) => granularity === "hour"
            ? `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())} ${p(x.getHours())}:00:00`
            : `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`;
        return { start: fmt(d), end: fmt(e) };
    }
}
