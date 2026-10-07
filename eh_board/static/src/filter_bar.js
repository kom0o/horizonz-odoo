/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * The global filter bar: relative-date presets resolved on the client (so the
 * viewer's timezone always wins) into a {start, end} the board applies to
 * every time-based item at once. */

import { _t } from "@web/core/l10n/translation";
import { Component } from "@odoo/owl";

export const DATE_PRESETS = [
    { key: "all", get label() { return _t("None"); } },
    { key: "today", get label() { return _t("Today"); } },
    { key: "yesterday", get label() { return _t("Yesterday"); } },
    { key: "tomorrow", get label() { return _t("Tomorrow"); } },
    { key: "this_week", get label() { return _t("This week"); } },
    { key: "last_week", get label() { return _t("Last week"); } },
    { key: "next_week", get label() { return _t("Next week"); } },
    { key: "this_month", get label() { return _t("This month"); } },
    { key: "last_month", get label() { return _t("Last month"); } },
    { key: "next_month", get label() { return _t("Next month"); } },
    { key: "this_quarter", get label() { return _t("This quarter"); } },
    { key: "last_quarter", get label() { return _t("Last quarter"); } },
    { key: "next_quarter", get label() { return _t("Next quarter"); } },
    { key: "this_year", get label() { return _t("This year"); } },
    { key: "last_year", get label() { return _t("Last year"); } },
    { key: "next_year", get label() { return _t("Next year"); } },
    { key: "wtd", get label() { return _t("Week to date"); } },
    { key: "mtd", get label() { return _t("Month to date"); } },
    { key: "qtd", get label() { return _t("Quarter to date"); } },
    { key: "ytd", get label() { return _t("Year to date"); } },
    { key: "last_7", get label() { return _t("Last 7 days"); } },
    { key: "last_30", get label() { return _t("Last 30 days"); } },
    { key: "last_90", get label() { return _t("Last 90 days"); } },
    { key: "last_365", get label() { return _t("Last 365 days"); } },
    { key: "custom", get label() { return _t("Custom range"); } },
];

function iso(d) {
    // Format the LOCAL date components. NEVER toISOString(): it converts to UTC,
    // so for any positive-UTC-offset timezone (e.g. Australia, UTC+10/11) a local
    // midnight becomes the previous day and every preset ("today", "this month",
    // ...) silently returned the wrong range. The presets are resolved on the
    // client precisely so the viewer's own timezone wins.
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

export function resolvePreset(key) {
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth(), d = now.getDate();
    const startOfDay = new Date(y, m, d);
    const mk = (a, b) => ({ start: iso(a), end: iso(b) });
    switch (key) {
        case "today":
            return mk(startOfDay, startOfDay);
        case "yesterday": {
            const day = new Date(y, m, d - 1);
            return mk(day, day);
        }
        case "tomorrow": {
            const day = new Date(y, m, d + 1);
            return mk(day, day);
        }
        case "this_week": {
            const dow = (now.getDay() + 6) % 7; // Monday-based
            return mk(new Date(y, m, d - dow), new Date(y, m, d - dow + 6));
        }
        case "wtd": {
            const dow = (now.getDay() + 6) % 7;
            return mk(new Date(y, m, d - dow), now);
        }
        case "last_week": {
            const dow = (now.getDay() + 6) % 7;
            return mk(new Date(y, m, d - dow - 7), new Date(y, m, d - dow - 1));
        }
        case "next_week": {
            const dow = (now.getDay() + 6) % 7;
            return mk(new Date(y, m, d - dow + 7), new Date(y, m, d - dow + 13));
        }
        case "this_month":
            return mk(new Date(y, m, 1), new Date(y, m + 1, 0));
        case "mtd":
            return mk(new Date(y, m, 1), now);
        case "last_month":
            return mk(new Date(y, m - 1, 1), new Date(y, m, 0));
        case "next_month":
            return mk(new Date(y, m + 1, 1), new Date(y, m + 2, 0));
        case "this_quarter": {
            const q = Math.floor(m / 3) * 3;
            return mk(new Date(y, q, 1), new Date(y, q + 3, 0));
        }
        case "qtd": {
            const q = Math.floor(m / 3) * 3;
            return mk(new Date(y, q, 1), now);
        }
        case "last_quarter": {
            const q = Math.floor(m / 3) * 3;
            return mk(new Date(y, q - 3, 1), new Date(y, q, 0));
        }
        case "next_quarter": {
            const q = Math.floor(m / 3) * 3;
            return mk(new Date(y, q + 3, 1), new Date(y, q + 6, 0));
        }
        case "this_year":
            return mk(new Date(y, 0, 1), new Date(y, 11, 31));
        case "ytd":
            return mk(new Date(y, 0, 1), now);
        case "last_year":
            return mk(new Date(y - 1, 0, 1), new Date(y - 1, 11, 31));
        case "next_year":
            return mk(new Date(y + 1, 0, 1), new Date(y + 1, 11, 31));
        case "last_7":
            return mk(new Date(y, m, d - 6), now);
        case "last_30":
            return mk(new Date(y, m, d - 29), now);
        case "last_90":
            return mk(new Date(y, m, d - 89), now);
        case "last_365":
            return mk(new Date(y, m, d - 364), now);
        default:
            return null;
    }
}

export class FilterBar extends Component {
    static template = "eh_board.FilterBar";
    static props = {
        preset: String,
        onPresetChange: Function,
        filters: { type: Array, optional: true },
        filterValues: { type: Object, optional: true },
        onFilterChange: { type: Function, optional: true },
        customStart: { type: String, optional: true },
        customEnd: { type: String, optional: true },
        onCustomDateChange: { type: Function, optional: true },
    };

    presets = DATE_PRESETS;

    get fieldFilters() {
        return (this.props.filters || []).filter((f) => f.type === "field");
    }
    get customInvalid() {
        return this.props.preset === "custom" && this.props.customStart
            && this.props.customEnd && this.props.customEnd < this.props.customStart;
    }
    valueOf(filter) {
        const v = (this.props.filterValues || {})[filter.id];
        return v && v.length ? v[0] : "";
    }
    isSelected(filter, value) {
        return String(value) === String(this.valueOf(filter));
    }
    onSelect(ev) {
        this.props.onPresetChange(ev.target.value);
    }
    onFieldSelect(filter, ev) {
        const raw = ev.target.value;
        if (!this.props.onFilterChange) return;
        if (raw === "") {
            this.props.onFilterChange(filter.id, []);
        } else {
            // preserve the option's original type (id numbers vs strings)
            const opt = filter.options.find((o) => String(o.value) === raw);
            this.props.onFilterChange(filter.id, [opt ? opt.value : raw]);
        }
    }
    onCustomInput(which, ev) {
        if (!this.props.onCustomDateChange) return;
        const start = which === "start" ? ev.target.value : (this.props.customStart || "");
        const end = which === "end" ? ev.target.value : (this.props.customEnd || "");
        this.props.onCustomDateChange(start, end);
    }
}
