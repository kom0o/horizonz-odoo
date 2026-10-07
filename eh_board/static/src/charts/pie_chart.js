/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Pie / doughnut / semi. Slices from the first measure across categories. */

import { uiText } from "../ui_text";

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { arcPath, chartColor, formatValue } from "./svg_util";
import { showTooltip, moveTooltip, hideTooltip } from "./tooltip";

const SIZE = 240;

export class PieChart extends Component {
    static template = "eh_board.PieChart";
    uiText = uiText;
    static props = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

    setup() {
        // Categories the user has clicked off in the legend (hidden slices).
        this.state = useState({ hidden: [] });
    }
    isHidden(i) { return this.state.hidden.includes(i); }
    toggleHidden(i) {
        this.state.hidden = this.isHidden(i)
            ? this.state.hidden.filter((x) => x !== i)
            : [...this.state.hidden, i];
    }

    get type() {
        return this.props.payload.type || "pie";
    }
    get display() {
        return (this.props.meta && this.props.meta.display) || {};
    }
    get isSemi() {
        return this.type === "semi" || !!this.display.semi_circle;
    }
    get showLegend() {
        return this.display.show_legend !== false;
    }
    get dataLabelType() {
        // Explicit choice wins; else fall back to the generic value-labels toggle.
        return this.display.data_label_type
            || (this.display.show_values === false ? "none" : "value");
    }
    get labels() {
        return this.props.payload.labels || [];
    }
    get values() {
        const s = (this.props.payload.series || [])[0];
        return s ? s.data : [];
    }
    get total() {
        return this.values.reduce((a, b, i) => a + (this.isHidden(i) ? 0 : (b || 0)), 0);
    }
    get legendItems() {
        // The legend shows EVERY category; a hidden one is muted and clickable.
        return this.labels.map((label, i) => ({
            label, index: i, color: this.color(i), hidden: this.isHidden(i),
        }));
    }
    get primarySeries() {
        return (this.props.payload.series || [])[0] || {};
    }
    color(index) {
        return chartColor(this.props.meta, 0, index, index);
    }
    fmt(value) {
        const p = this.props.payload;
        const s = this.primarySeries;
        return formatValue(value, s.number_format || p.number_format,
            s.currency || p.currency, s.unit || p.unit || "");
    }

    get slices() {
        const total = this.total || 1;
        const semi = this.isSemi;
        const span = semi ? Math.PI : 2 * Math.PI;
        const start = semi ? Math.PI : -Math.PI / 2;
        const cx = SIZE / 2;
        const cy = semi ? SIZE * 0.75 : SIZE / 2;
        const rOuter = semi ? SIZE * 0.42 : SIZE * 0.44;
        const rInner = this.type === "pie" ? 0 : rOuter * 0.58;
        // Place labels on the coloured band: mid-ring for a doughnut, ~65%
        // radius for a full pie, so they read on the fill, not off the edge.
        const labelR = rInner > 0 ? (rInner + rOuter) / 2 : rOuter * 0.62;
        const labelType = this.dataLabelType;
        let angle = start;
        const out = [];
        this.labels.forEach((label, i) => {
            if (this.isHidden(i)) return;   // clicked-off in the legend
            const v = this.values[i] || 0;
            const slice = (v / total) * span;
            const path = arcPath(cx, cy, rOuter, rInner, angle, angle + slice);
            const mid = angle + slice / 2;
            angle += slice;
            const pct = total ? Math.round((v / total) * 100) : 0;
            let labelText = "";
            if (labelType === "value") labelText = this.fmt(v);
            else if (labelType === "percent") labelText = pct + "%";
            out.push({
                path, label, value: v, index: i,
                color: this.color(i), pct, labelText,
                showLabel: labelType !== "none" && slice > 0.28,
                lx: cx + labelR * Math.cos(mid),
                ly: cy + labelR * Math.sin(mid) + 4,
            });
        });
        return out;
    }

    get viewBox() {
        return `0 0 ${SIZE} ${SIZE}`;
    }
    get centerLabel() {
        return this.fmt(this.total);
    }

    onSliceClick(slice) {
        if (this.props.onDrill) {
            this.props.onDrill({ label: slice.label, index: slice.index });
        }
    }
    onSliceHover(ev, slice) {
        showTooltip(ev, slice.label, [
            { label: _t("Value"), value: this.fmt(slice.value), color: slice.color },
            { label: _t("Share"), value: slice.pct + "%", color: slice.color },
        ]);
    }
    onMove(ev) {
        moveTooltip(ev);
    }
    onLeave() {
        hideTooltip();
    }
}
