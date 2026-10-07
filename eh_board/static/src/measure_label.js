/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * One place that names the percentage companion column.
 *
 * WHY. "% of grand total" is only a SHARE when the aggregate is additive: the
 * rows of a Sum or a Count add up to the total, so each row's percentage is its
 * slice and the column adds to 100%. For an Average, a Min, a Max or a Distinct
 * count it does not: the total-grain figure is itself an average (or a min, or
 * a max), so dividing a row by it yields a RATIO against that figure, the column
 * runs well past 100%, and a reader who takes 331% as "a third of all margin" is
 * badly misled. Same number, different meaning, so it needs a different name.
 *
 * The value itself is unchanged and correct either way: it is always
 * row / total-grain, computed by a dedicated no-dimension read.
 */

import { _t } from "@web/core/l10n/translation";

/** Aggregates whose rows genuinely add up to the total-grain figure. */
const ADDITIVE = ["sum", "count"];

/** What the total-grain figure IS, for the aggregates that are not additive. */
const GRAIN = {
    avg: () => _t("avg"),
    min: () => _t("min"),
    max: () => _t("max"),
    count_distinct: () => _t("distinct"),
};

/** The share wording, unchanged so existing translations keep matching. */
const SHARE = {
    percent_row: () => _t("% row"),
    percent_column: () => _t("% column"),
    percent_grand: () => _t("% grand"),
};

/** The scope word on its own, for the ratio wording. */
const SCOPE = {
    percent_row: () => _t("row"),
    percent_column: () => _t("column"),
    percent_grand: () => _t("grand"),
};

/**
 * Suffix for the percentage column, honest about what the number means.
 *
 * Additive aggregates keep the familiar share wording ("% grand", "% row",
 * "% column"). Everything else says what it is a percentage OF, so
 * "Margin · % of grand avg" reads as "331% of the overall average margin"
 * rather than as a third of all margin.
 *
 * `formula` deliberately keeps the share wording: a calculated measure may be
 * additive (a + b over two sums) or not (a / b), and nothing here can tell
 * which.
 *
 * @param {string} calculation "percent_grand" | "percent_row" | "percent_column"
 * @param {string} [aggregate] the measure's aggregate, when known
 * @returns {string}
 */
export function percentSuffix(calculation, aggregate) {
    const key = SHARE[calculation] ? calculation : "percent_grand";
    const grain = GRAIN[aggregate];
    if (!grain || ADDITIVE.includes(aggregate)) {
        return SHARE[key]();
    }
    return `${_t("% of")} ${SCOPE[key]()} ${grain()}`;
}

/**
 * Full header for the percentage companion column.
 *
 * @param {string} label the measure's own label
 * @param {string} calculation the table calculation on the measure
 * @param {string} [aggregate] the measure's aggregate, when known
 * @returns {string}
 */
export function percentColumnLabel(label, calculation, aggregate) {
    return `${label} · ${percentSuffix(calculation, aggregate)}`;
}
