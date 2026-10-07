/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Additional original-SVG chart types: radar, funnel and scatter. Each follows
 * the same props contract and shared helpers as the core charts. */

import { uiText } from "../ui_text";

import { _t } from "@web/core/l10n/translation";

import { Component, useState } from "@odoo/owl";
import { chartColor, formatValue, linePath, niceScale, arcPath } from "./svg_util";
import { showTooltip, moveTooltip, hideTooltip } from "./tooltip";

/** Shared interactive-legend state: click a category to hide/show it. */
function useLegendToggle(comp) {
    comp.state = useState({ hidden: [] });
    comp.isHidden = (i) => comp.state.hidden.includes(i);
    comp.toggleHidden = (i) => {
        comp.state.hidden = comp.isHidden(i)
            ? comp.state.hidden.filter((x) => x !== i)
            : [...comp.state.hidden, i];
    };
}

const SIZE = 300;
const CHART_PROPS = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

function colorFor(comp, seriesIndex = 0, categoryIndex = null, naturalIndex = null) {
    return chartColor(comp.props.meta, seriesIndex, categoryIndex, naturalIndex);
}

function formatFor(comp, value, series = null) {
    const payload = comp.props.payload;
    return formatValue(value,
        (series && series.number_format) || payload.number_format,
        (series && series.currency) || payload.currency,
        (series && series.unit) || payload.unit || "");
}

export class RadarChart extends Component {
    static template = "eh_board.RadarChart";
    uiText = uiText;
    static props = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

    setup() { useLegendToggle(this); }
    get labels() { return this.props.payload.labels || []; }
    get series() { return this.props.payload.series || []; }
    get legendItems() {
        return this.series.map((s, i) => ({
            label: s.label, index: i, color: colorFor(this, i), hidden: this.isHidden(i) }));
    }
    get max() {
        let m = 0;
        this.series.forEach((s, si) => {
            if (this.isHidden(si)) return;
            for (const v of s.data) m = Math.max(m, v || 0);
        });
        return m || 1;
    }
    get geo() { return { cx: SIZE / 2, cy: SIZE / 2, r: SIZE * 0.30 }; }
    angle(i) { return -Math.PI / 2 + (i / (this.labels.length || 1)) * 2 * Math.PI; }

    get axes() {
        const { cx, cy, r } = this.geo;
        return this.labels.map((label, i) => {
            const a = this.angle(i);
            const s = String(label == null ? "" : label);
            return {
                label: s.length > 12 ? s.slice(0, 11) + "…" : s,
                x2: cx + r * Math.cos(a), y2: cy + r * Math.sin(a),
                lx: cx + (r + 14) * Math.cos(a), ly: cy + (r + 14) * Math.sin(a),
                anchor: Math.abs(Math.cos(a)) < 0.3 ? "middle" : (Math.cos(a) > 0 ? "start" : "end"),
            };
        });
    }
    get rings() {
        const { cx, cy, r } = this.geo;
        return [0.25, 0.5, 0.75, 1].map((f) => {
            const pts = this.labels.map((_, i) => {
                const a = this.angle(i);
                return { x: cx + r * f * Math.cos(a), y: cy + r * f * Math.sin(a) };
            });
            return pts.length ? linePath(pts) + " Z" : "";
        });
    }
    get polygons() {
        const { cx, cy, r } = this.geo;
        return this.series.map((s, si) => {
            if (this.isHidden(si)) return null;
            const pts = this.labels.map((_, i) => {
                const a = this.angle(i);
                const ratio = (s.data[i] || 0) / this.max;
                return { x: cx + r * ratio * Math.cos(a), y: cy + r * ratio * Math.sin(a) };
            });
            return { path: pts.length ? linePath(pts) + " Z" : "", color: colorFor(this, si), points: pts, label: s.label };
        }).filter(Boolean);
    }
    get viewBox() { return `0 0 ${SIZE} ${SIZE}`; }

    onHover(ev, i) {
        const rows = this.series.map((s, si) => ({
            label: s.label, value: formatFor(this, s.data[i] || 0, s), color: colorFor(this, si, i, si),
        }));
        showTooltip(ev, this.labels[i], rows);
    }
    onMove(ev) { moveTooltip(ev); }
    onLeave() { hideTooltip(); }
}

const FW = 420, FH = 300;

export class FunnelChart extends Component {
    static template = "eh_board.FunnelChart";
    static props = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

    get rows() {
        const labels = this.props.payload.labels || [];
        const data = (this.props.payload.series || [])[0];
        const vals = data ? data.data : [];
        const rows = labels.map((label, i) => ({ label, value: vals[i] || 0, index: i }));
        return this.props.payload.type === "pyramid"
            ? rows.sort((a, b) => a.value - b.value)
            : rows.sort((a, b) => b.value - a.value);
    }
    get max() { return Math.max(1, ...this.rows.map((r) => r.value)); }
    // Below a band height that fits the label, drop the on-segment text and rely
    // on the hover tooltip instead of a crowded overlap.
    get showLabels() { return this.rows.length <= 9; }
    get segments() {
        const n = this.rows.length || 1;
        const gap = 4;
        const h = (FH - gap * (n - 1)) / n;
        const cx = FW / 2;
        const top0 = this.props.payload.type === "pyramid";
        return this.rows.map((r, i) => {
            const wTop = (this.rows[i].value / this.max) * FW;
            const next = this.rows[i + 1] ? this.rows[i + 1].value : r.value;
            const wBot = (next / this.max) * FW;
            const y = i * (h + gap);
            const pts = [
                [cx - wTop / 2, y], [cx + wTop / 2, y],
                [cx + wBot / 2, y + h], [cx - wBot / 2, y + h],
            ];
            // Percent of the top band; guard 0/0 (all-zero series) -> 0, not NaN.
            const base = this.rows[0] && this.rows[0].value;
            return {
                path: `M${pts.map((p) => p.join(",")).join(" L")} Z`,
                color: colorFor(this, 0, i, i), label: r.label, value: r.value,
                cx, cy: y + h / 2, index: r.index,
                pct: base ? Math.round((r.value / base) * 100) : 0,
            };
        });
    }
    get viewBox() { return `0 0 ${FW} ${FH}`; }

    onClick(seg) { if (this.props.onDrill) this.props.onDrill({ label: seg.label, index: seg.index }); }
    onHover(ev, seg) {
        showTooltip(ev, seg.label, [{ label: _t("Value"), value: formatFor(this, seg.value), color: seg.color }]);
    }
    onMove(ev) { moveTooltip(ev); }
    onLeave() { hideTooltip(); }
}

const SW = 460, SH = 300;
const SP = { top: 16, right: 16, bottom: 50, left: 62 };

export class ScatterChart extends Component {
    static template = "eh_board.ScatterChart";
    static props = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

    get plot() { return { x: SP.left, y: SP.top, w: SW - SP.left - SP.right, h: SH - SP.top - SP.bottom }; }
    /** Two measures -> (x, y); one measure -> (index, y). */
    get raw() {
        const labels = this.props.payload.labels || [];
        const series = this.props.payload.series || [];
        const ys = series[0] ? series[0].data : [];
        const xs = series[1] ? series[1].data : labels.map((_, i) => i);
        return labels.map((label, i) => ({ label, x: xs[i] || 0, y: ys[i] || 0 }));
    }
    get xScale() { return niceScale(Math.min(0, ...this.raw.map((p) => p.x)), Math.max(1, ...this.raw.map((p) => p.x)), 5); }
    get yScale() { return niceScale(Math.min(0, ...this.raw.map((p) => p.y)), Math.max(1, ...this.raw.map((p) => p.y)), 5); }
    xPx(v) { const s = this.xScale; return this.plot.x + ((v - s.min) / (s.max - s.min || 1)) * this.plot.w; }
    yPx(v) { const s = this.yScale; return this.plot.y + this.plot.h - ((v - s.min) / (s.max - s.min || 1)) * this.plot.h; }
    get points() {
        return this.raw.map((p, i) => ({ ...p, cx: this.xPx(p.x), cy: this.yPx(p.y), color: colorFor(this, 0, i, 0), index: i }));
    }
    get yGrid() { return this.yScale.ticks.map((t) => ({ label: formatFor(this, t, (this.props.payload.series || [])[0]), y: this.yPx(t) })); }
    get xGrid() { return this.xScale.ticks.map((t) => ({ label: formatFor(this, t, (this.props.payload.series || [])[1]), x: this.xPx(t) })); }
    get xLabel() {
        const series = this.props.payload.series || [];
        return series[1] ? series[1].label : _t("Category index");
    }
    get yLabel() {
        const series = this.props.payload.series || [];
        return series[0] ? series[0].label : _t("Value");
    }
    get viewBox() { return `0 0 ${SW} ${SH}`; }

    onClick(point) {
        if (this.props.onDrill) this.props.onDrill({
            label: point.label, index: point.index,
        });
    }
    onKey(ev, point) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onClick(point);
        }
    }
    onHover(ev, p) {
        const series = this.props.payload.series || [];
        showTooltip(ev, p.label, [
            { label: this.xLabel, value: formatFor(this, p.x, series[1]), color: p.color },
            { label: this.yLabel, value: formatFor(this, p.y, series[0]), color: p.color },
        ]);
    }
    onMove(ev) { moveTooltip(ev); }
    onLeave() { hideTooltip(); }
}

const PSZ = 300;

/** Polar area: equal-angle slices whose radius scales so slice AREA tracks the
 *  value (radius = sqrt(v/max)), a gentler read than a bare pie. */
export class PolarChart extends Component {
    static template = "eh_board.PolarChart";
    uiText = uiText;
    static props = CHART_PROPS;
    setup() { useLegendToggle(this); }
    get labels() { return this.props.payload.labels || []; }
    get data() { const s = (this.props.payload.series || [])[0]; return s ? s.data : []; }
    get max() {
        return Math.max(1, ...this.data.map((v, i) => (this.isHidden(i) ? 0 : (v || 0))));
    }
    get legendItems() {
        return this.labels.map((label, i) => ({
            label, index: i, color: colorFor(this, 0, i, i), hidden: this.isHidden(i) }));
    }
    get rings() {
        const c = PSZ / 2, rMax = PSZ * 0.42;
        return [0.25, 0.5, 0.75, 1].map((f) => ({ c, r: rMax * f }));
    }
    get slices() {
        const cx = PSZ / 2, cy = PSZ / 2, rMax = PSZ * 0.42, n = this.labels.length || 1;
        const out = [];
        this.labels.forEach((label, i) => {
            if (this.isHidden(i)) return;
            const a0 = -Math.PI / 2 + (i / n) * 2 * Math.PI;
            const a1 = -Math.PI / 2 + ((i + 1) / n) * 2 * Math.PI;
            const r = rMax * Math.sqrt(Math.max(0, (this.data[i] || 0) / this.max));
            out.push({ path: arcPath(cx, cy, r, 0, a0, a1), color: colorFor(this, 0, i, i),
                       label, value: this.data[i] || 0, index: i });
        });
        return out;
    }
    get viewBox() { return `0 0 ${PSZ} ${PSZ}`; }
    onClick(s) { if (this.props.onDrill) this.props.onDrill({ label: s.label, index: s.index }); }
    onHover(ev, s) { showTooltip(ev, s.label, [{ label: _t("Value"), value: formatFor(this, s.value), color: s.color }]); }
    onMove(ev) { moveTooltip(ev); }
    onLeave() { hideTooltip(); }
}

/** Radial bar: one concentric ring per category, filled to value/max. */
export class RadialChart extends Component {
    static template = "eh_board.RadialChart";
    uiText = uiText;
    static props = CHART_PROPS;
    setup() { useLegendToggle(this); }
    get labels() { return this.props.payload.labels || []; }
    get data() { const s = (this.props.payload.series || [])[0]; return s ? s.data : []; }
    get max() {
        return Math.max(1, ...this.data.map((v, i) => (this.isHidden(i) ? 0 : (v || 0))));
    }
    get legendItems() {
        return this.labels.map((label, i) => ({
            label, index: i, color: colorFor(this, 0, i, i), hidden: this.isHidden(i) }));
    }
    get rings() {
        const cx = PSZ / 2, cy = PSZ / 2, n = Math.max(1, this.labels.length);
        const rOuter = PSZ * 0.45, rInner = PSZ * 0.13;
        const band = (rOuter - rInner) / n, gap = band * 0.3;
        const full = Math.PI * 1.9999, a0 = -Math.PI / 2;
        const out = [];
        this.labels.forEach((label, i) => {
            if (this.isHidden(i)) return;
            const ro = rOuter - i * band, ri = ro - (band - gap);
            const frac = Math.min(1, (this.data[i] || 0) / this.max);
            out.push({
                track: arcPath(cx, cy, ro, ri, a0, a0 + full),
                path: arcPath(cx, cy, ro, ri, a0, a0 + full * frac),
                color: colorFor(this, 0, i, i), label, value: this.data[i] || 0, index: i,
            });
        });
        return out;
    }
    get viewBox() { return `0 0 ${PSZ} ${PSZ}`; }
    onClick(r) { if (this.props.onDrill) this.props.onDrill({ label: r.label, index: r.index }); }
    onHover(ev, r) { showTooltip(ev, r.label, [{ label: _t("Value"), value: formatFor(this, r.value), color: r.color }]); }
    onMove(ev) { moveTooltip(ev); }
    onLeave() { hideTooltip(); }
}

/** Rose (Nightingale / coxcomb): equal-angle petals whose radius is LINEARLY
 *  proportional to value (unlike Polar, which is area-proportional via sqrt),
 *  with a small angular gap so it reads as a flower. */
export class RoseChart extends Component {
    static template = "eh_board.RoseChart";
    uiText = uiText;
    static props = CHART_PROPS;
    setup() { useLegendToggle(this); }
    get labels() { return this.props.payload.labels || []; }
    get data() { const s = (this.props.payload.series || [])[0]; return s ? s.data : []; }
    get max() {
        return Math.max(1, ...this.data.map((v, i) => (this.isHidden(i) ? 0 : (v || 0))));
    }
    get legendItems() {
        return this.labels.map((label, i) => ({
            label, index: i, color: colorFor(this, 0, i, i), hidden: this.isHidden(i) }));
    }
    get rings() {
        const c = PSZ / 2, rMax = PSZ * 0.42;
        return [0.25, 0.5, 0.75, 1].map((f) => ({ c, r: rMax * f }));
    }
    get petals() {
        const cx = PSZ / 2, cy = PSZ / 2, rMax = PSZ * 0.42;
        const n = this.labels.length || 1;
        const step = (2 * Math.PI) / n;
        const gap = n > 1 ? step * 0.08 : 0;   // petal separation for the flower look
        const out = [];
        this.labels.forEach((label, i) => {
            if (this.isHidden(i)) return;
            const mid = -Math.PI / 2 + (i + 0.5) * step;
            const a0 = mid - step / 2 + gap / 2;
            const a1 = mid + step / 2 - gap / 2;
            // Linear radius: a value twice as large reaches twice as far.
            // Clamp to [0,1] so a negative value never draws an inverted petal.
            const r = rMax * Math.max(0, Math.min(1, (this.data[i] || 0) / this.max));
            out.push({ path: arcPath(cx, cy, r, 0, a0, a1), color: colorFor(this, 0, i, i),
                       label, value: this.data[i] || 0, index: i });
        });
        return out;
    }
    get viewBox() { return `0 0 ${PSZ} ${PSZ}`; }
    onClick(s) { if (this.props.onDrill) this.props.onDrill({ label: s.label, index: s.index }); }
    onHover(ev, s) { showTooltip(ev, s.label, [{ label: _t("Value"), value: formatFor(this, s.value), color: s.color }]); }
    onMove(ev) { moveTooltip(ev); }
    onLeave() { hideTooltip(); }
}

/** Bullet: a dense actual-vs-target bar with qualitative bands (KPI payload). */
export class BulletChart extends Component {
    static template = "eh_board.BulletChart";
    uiText = uiText;
    static props = CHART_PROPS;
    get value() { return this.props.payload.value || 0; }
    get target() { return this.props.payload.target || 0; }
    get scale() { return Math.max(this.value, this.target, 1) * 1.15; }
    get valuePct() { return (this.value / this.scale) * 100; }
    get targetPct() { return this.target ? (this.target / this.scale) * 100 : null; }
    get bands() { return [{ w: 65, o: 0.14 }, { w: 85, o: 0.09 }, { w: 100, o: 0.05 }]; }
    get met() { return this.target && this.value >= this.target; }
    fmt(v) { return formatFor(this, v); }
    get clickable() {
        const m = this.props.meta;
        return !!(m && m.model && m.click_action !== "none" && this.props.onDrill);
    }
    onClick() { if (this.clickable) this.props.onDrill({}); }
}

/** Heat map: a coloured grid of the first measure across two dimensions. */
export class HeatmapChart extends Component {
    static template = "eh_board.HeatmapChart";
    static props = CHART_PROPS;
    get grid() {
        const p = this.props.payload;
        const rows = p.rows || [];
        const mk = (p.measure_keys || [])[0];
        // With only one dimension there is no column axis: show a single named
        // _t("Value") column instead of an anonymous "-" so it still reads cleanly.
        const single = !rows.some((r) => (r.labels || []).length > 1);
        const colName = (p.measure_labels && p.measure_labels[mk]) || _t("Value");
        const rowLabels = [], colLabels = [], seenR = {}, seenC = {}, cells = {};
        let max = 0;
        for (const r of rows) {
            const rl = (r.labels || [])[0] || "-";
            const cl = (r.labels || [])[1] || (single ? colName : "-");
            if (!(rl in seenR)) { seenR[rl] = 1; rowLabels.push(rl); }
            if (!(cl in seenC)) { seenC[cl] = 1; colLabels.push(cl); }
            const v = (r.values || {})[mk] || 0;
            cells[JSON.stringify([rl, cl])] = v;
            max = Math.max(max, Math.abs(v));
        }
        const body = rowLabels.slice(0, 40).map((rl) => ({
            label: rl,
            cells: colLabels.slice(0, 30).map((cl) => {
                const v = cells[JSON.stringify([rl, cl])] || 0;
                const t = max ? Math.abs(v) / max : 0;
                // Diverging: negatives red, positives mint.
                const hue = v < 0 ? "var(--eh-board-series-6)" : "var(--eh-board-accent)";
                return {
                    text: formatValue(v, p.number_format, p.currency, p.unit || ""),
                    style: v ? `background:color-mix(in srgb, ${hue} ${Math.round((0.08 + t * 0.72) * 100)}%, transparent);` : "",
                };
            }),
        }));
        return { rowLabels: rowLabels.slice(0, 40), colLabels: colLabels.slice(0, 30), body };
    }
}
