/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Grouped list / table: one row per category, one column per measure. */

import { Component, markup, useState, onWillUpdateProps } from "@odoo/owl";
import { formatValue } from "./svg_util";
import { matchRule, textOn } from "../conditional";
import { percentColumnLabel } from "../measure_label";

export class ListWidget extends Component {
    static template = "eh_board.ListWidget";
    static props = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

    setup() {
        this.state = useState({ page: 1, pageSize: 25 });
        onWillUpdateProps(() => { this.state.page = 1; });
    }

    get measureKeys() {
        return this.props.payload.measure_keys || [];
    }
    get isRecordList() {
        return !!this.props.payload.record_list;
    }
    get seriesByKey() {
        return Object.fromEntries((this.props.payload.series || []).map((series) => [series.key, series]));
    }
    _fmt(value, key) {
        const p = this.props.payload;
        const series = this.seriesByKey[key] || {};
        return formatValue(value, series.number_format || p.number_format,
            series.currency || p.currency, series.unit || p.unit || "");
    }
    get columns() {
        if (this.isRecordList) {
            return (this.props.payload.columns || []).map((column) => ({
                label: column.label || column.name,
                numeric: ["integer", "float", "monetary"].includes(column.type),
            }));
        }
        const series = this.props.payload.series || [];
        const calculations = this.props.payload.measure_calculations || {};
        const aggregates = this.props.payload.measure_aggregates || {};
        const columns = [];
        for (const seriesItem of series) {
            columns.push({ label: seriesItem.label, numeric: true });
            const calculation = calculations[seriesItem.key];
            if (calculation && calculation !== "none") {
                columns.push({
                    label: percentColumnLabel(
                        seriesItem.label, calculation, aggregates[seriesItem.key]),
                    numeric: true, percentage: true,
                });
            }
        }
        return columns;
    }
    get rules() {
        return (this.props.meta && this.props.meta.conditional_rules) || [];
    }
    get colMax() {
        const rows = this.props.payload.rows || [];
        const max = {};
        for (const k of this.measureKeys) {
            max[k] = Math.max(1, ...rows.map((r) => Math.abs(r.values[k] || 0)));
        }
        return max;
    }
    get allRows() {
        const p = this.props.payload, cmax = this.colMax, rules = this.rules;
        if (this.isRecordList) {
            return (p.rows || []).map((row, index) => ({
                index,
                id: row.id,
                label: row.label || "",
                cells: (row.cells || []).map((cell) => ({
                    text: this._recordText(cell),
                    numeric: ["integer", "float", "monetary"].includes(cell.type),
                    style: "", bar: 0, barColor: "",
                })),
            }));
        }
        return (p.rows || []).map((r, i) => ({
            index: i,
            label: (r.labels || []).filter((label) =>
                label !== null && label !== undefined && label !== "").join(" / "),
            cells: this.measureKeys.flatMap((k, ki) => {
                const v = r.values[k] || 0;
                const m = matchRule(rules, v, ki);
                let style = "", bar = 0, barColor = "";
                if (m && m.style === "fill") {
                    style = `background:${m.color};color:${textOn(m.color)};`;
                } else if (m && m.style === "bar") {
                    bar = Math.round((Math.abs(v) / cmax[k]) * 100);
                    barColor = m.color;
                } else if (m) {
                    style = `color:${m.color};font-weight:700;`;
                }
                const cells = [{ text: this._fmt(v, k), style, bar, barColor, numeric: true }];
                if ((p.measure_calculations || {})[k]
                        && (p.measure_calculations || {})[k] !== "none") {
                    cells.push({
                        text: this._percent(v, (p.grand_total || {})[k]),
                        style: "", bar: 0, barColor: "", numeric: true, percentage: true,
                    });
                }
                return cells;
            }),
        }));
    }
    get totalRows() { return this.allRows.length; }
    get totalPages() { return Math.max(1, Math.ceil(this.totalRows / this.state.pageSize)); }
    get page() { return Math.min(this.state.page, this.totalPages); }
    get rows() {
        const start = (this.page - 1) * this.state.pageSize;
        return this.allRows.slice(start, start + this.state.pageSize);
    }
    get rangeLabel() {
        if (!this.totalRows) return "0 rows";
        const start = (this.page - 1) * this.state.pageSize + 1;
        const end = Math.min(this.totalRows, start + this.state.pageSize - 1);
        return `${start}–${end} of ${this.totalRows}`;
    }
    setPage(delta) {
        this.state.page = Math.max(1, Math.min(this.totalPages, this.page + delta));
    }
    setPageSize(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.pageSize = [10, 25, 50, 100].includes(value) ? value : 25;
        this.state.page = 1;
    }
    _recordText(cell) {
        if (!cell) return "";
        if (["integer", "float", "monetary"].includes(cell.type)) {
            return formatValue(cell.value, "plain");
        }
        return cell.text === null || cell.text === undefined ? "" : String(cell.text);
    }
    _percent(value, denominator) {
        const n = Number(value) || 0;
        const d = Number(denominator) || 0;
        if (!d) return "0%";
        const pct = n / d * 100;
        return `${pct.toFixed(1).replace(/\.0$/, "")}%`;
    }
    onRowClick(row) {
        if (this.props.onDrill) {
            if (this.isRecordList && row.id) {
                this.props.onDrill({ label: row.label, domain: [["id", "=", row.id]] });
            } else {
                this.props.onDrill({ label: row.label, index: row.index });
            }
        }
    }
}

export class ContentWidget extends Component {
    static template = "eh_board.ContentWidget";
    static props = {
        payload: Object,
        meta: { type: Object, optional: true },
        onDrill: { type: Function, optional: true },
    };

    get isTodo() {
        return (this.props.payload.type || "richtext") === "todo";
    }
    get html() {
        // Content is authored by Builders (a trusted role), so render it as
        // markup. Untrusted input never reaches this widget.
        return markup(this.props.payload.content || "");
    }
    get todoLines() {
        // Content is sanitized HTML from the rich editor (block elements + <br>),
        // NOT plain newlines - split on block boundaries and strip tags so each
        // checklist item is clean text instead of showing literal <p>/<div> tags.
        const html = this.props.payload.content || "";
        const doc = new DOMParser().parseFromString(
            html.replace(/<\/(p|div|li|h[1-6]|tr)>/gi, "\n").replace(/<br\s*\/?>/gi, "\n"),
            "text/html");
        return (doc.body.textContent || "")
            .split("\n").map((l) => l.trim()).filter(Boolean);
    }
}
