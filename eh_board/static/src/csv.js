/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * RFC 4180 CSV cell escaping + spreadsheet formula-injection guard. A label
 * like "Acme, Inc." must not shift columns, and "=cmd|..." must not execute
 * when the file is opened in Excel / Sheets. */

import { _t } from "@web/core/l10n/translation";
import { percentColumnLabel } from "./measure_label";

export function csvCell(v) {
    let s = v === null || v === undefined ? "" : String(v);
    // Neutralise a leading formula trigger (= + - @, tab, CR) before any quoting.
    if (/^[=+\-@\t\r]/.test(s)) {
        s = "'" + s;
    }
    // Quote if the value contains a comma, quote, or newline; double inner quotes.
    if (/[",\n\r]/.test(s)) {
        s = '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
}

export function csvRow(cells) {
    return cells.map(csvCell).join(",");
}

function skey(value) {
    return value === null || value === undefined ? "∅" : String(value);
}

function percent(value, denominator) {
    const n = Number(value) || 0;
    const d = Number(denominator) || 0;
    if (!d) return "0%";
    return `${(n / d * 100).toFixed(1).replace(/\.0$/, "")}%`;
}

/** Flatten any table-shaped payload into exactly what CSV/accessibility should
 * expose. List percentages stay adjacent to their values; pivot percentages
 * use the same row/column/grand denominators as the visible matrix. */
export function payloadTable(payload) {
    const p = payload || {};
    if (p.record_list) {
        return {
            headers: (p.columns || []).map((column) => column.label || column.name),
            rows: (p.rows || []).map((row) =>
                (row.cells || []).map((cell) =>
                    cell.text === null || cell.text === undefined ? "" : cell.text)),
        };
    }

    const keys = p.measure_keys || [];
    const seriesLabels = Object.fromEntries(
        (p.series || []).map((series) => [series.key, series.label || series.key]));
    const labels = { ...seriesLabels, ...(p.measure_labels || {}) };
    const calculations = ["table", "pivot"].includes(p.category)
        ? (p.measure_calculations || {}) : {};
    const aggregates = p.measure_aggregates || {};
    const descriptors = [];
    for (const key of keys) {
        descriptors.push({ key, label: labels[key] || key });
        const calculation = calculations[key];
        if (calculation && calculation !== "none") {
            descriptors.push({
                key, calculation,
                label: percentColumnLabel(
                    labels[key] || key, calculation, aggregates[key]),
            });
        }
    }

    const pivot = p.category === "pivot";
    const hasColumn = pivot && p.has_col;
    const axisHeaders = pivot
        ? [p.row_dim_label || _t("Rows"), ...(hasColumn ? [p.col_dim_label || _t("Columns")] : [])]
        : [_t("Category")];
    const rows = (p.rows || []).map((row) => {
        const rowLabels = row.labels || [];
        const axes = pivot
            ? [rowLabels[0] || "", ...(hasColumn ? [rowLabels[1] || ""] : [])]
            : [rowLabels.filter((label) =>
                label !== null && label !== undefined && label !== "").join(" / ")];
        const values = descriptors.map((descriptor) => {
            const value = (row.values || {})[descriptor.key] || 0;
            if (!descriptor.calculation) return value;
            let denominator = (p.grand_total || {})[descriptor.key] || 0;
            if (pivot && descriptor.calculation === "percent_row") {
                denominator = ((p.row_totals || {})[skey((row.keys || [])[0])] || {})[
                    descriptor.key] || 0;
            } else if (pivot && descriptor.calculation === "percent_column" && hasColumn) {
                denominator = ((p.col_totals || {})[skey((row.keys || [])[1])] || {})[
                    descriptor.key] || 0;
            }
            return percent(value, denominator);
        });
        return [...axes, ...values];
    });
    return { headers: [...axisHeaders, ...descriptors.map((column) => column.label)], rows };
}
