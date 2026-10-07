/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * On-canvas slicer: a field's values as chips or a compact, scrollable list.
 * Clicking a value cross-filters
 * every widget on the board (reuses the onDrill channel with a `slice` payload,
 * so no extra callback plumbing). Active chips reflect the live cross-filters. */

import { Component, useState } from "@odoo/owl";

export class SlicerWidget extends Component {
    static template = "eh_board.SlicerWidget";
    static props = {
        payload: Object,
        meta: { type: Object, optional: true },
        onDrill: { type: Function, optional: true },
        crossFilters: { type: Array, optional: true },
    };

    setup() {
        this.state = useState({ search: "" });
    }
    get field() { return this.props.payload.field; }
    get values() { return this.props.payload.values || []; }
    get compact() {
        const mode = (this.props.meta?.chart_options || {}).slicer_display || "auto";
        if (mode === "list") return true;
        if (mode === "chips") return false;
        // Use the full set, so searching never changes the control's layout.
        return this.values.length > 10;
    }
    get filteredValues() {
        const q = (this.state.search || "").toLowerCase().trim();
        if (!q) return this.values;
        return this.values.filter((v) => String(v.label).toLowerCase().includes(q));
    }
    get activeKeys() {
        const cf = this.props.crossFilters || [];
        return new Set(cf.filter((c) => c.field === this.field).map((c) => String(c.value)));
    }
    get hasActive() { return this.activeKeys.size > 0; }
    isActive(v) { return this.activeKeys.has(String(v.key)); }
    toggle(v) {
        if (this.props.onDrill) {
            this.props.onDrill({ slice: { field: this.field, value: v.key, label: v.label } });
        }
    }
    clearAll() {
        // Toggle off every currently-active value for this slicer's field.
        this.values.filter((v) => this.isActive(v)).forEach((v) => this.toggle(v));
    }
    onListKeydown(ev) {
        if (!this.compact || !["ArrowDown", "ArrowUp", "Home", "End"].includes(ev.key)) return;
        const buttons = Array.from(ev.currentTarget.querySelectorAll(".eh_board_slicer_chip"));
        const index = buttons.indexOf(ev.target);
        if (index < 0 || !buttons.length) return;
        ev.preventDefault();
        const next = ev.key === "Home" ? 0 : ev.key === "End" ? buttons.length - 1
            : Math.max(0, Math.min(buttons.length - 1, index + (ev.key === "ArrowDown" ? 1 : -1)));
        buttons[next].focus();
    }
}
