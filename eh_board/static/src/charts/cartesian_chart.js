/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * One parametric Cartesian chart for bar, horizontal bar, stacked column,
 * line and area. Reads the built payload and computes all geometry here, so
 * the template only maps arrays to SVG nodes and stays trivial to audit. */

import { uiText } from "../ui_text";

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { niceScale, chartColor, formatValue, linePath, smoothPath } from "./svg_util";
import { categoryLabelWidth, wrapCategoryLabel } from "./category_labels";
import { _t } from "@web/core/l10n/translation";
import { showTooltip, moveTooltip, hideTooltip } from "./tooltip";

const W = 480;
const H = 280;
const CROWDED_CATEGORY_ANGLE = 65;
const CATEGORY_LINE_HEIGHT = 14;

export class CartesianChart extends Component {
    static template = "eh_board.CartesianChart";
    uiText = uiText;
    static props = { payload: Object, meta: { type: Object, optional: true }, onDrill: { type: Function, optional: true } };

    setup() {
        // Series the user clicked off in the legend.
        this.state = useState({ hidden: [], zoomStart: 0, zoomSize: 0, chartWidth: W });
        this.chartRef = useRef("chart");
        let observer;
        const resize = () => {
            const width = this.chartRef.el && this.chartRef.el.clientWidth;
            if (width > 0 && Math.abs(width - this.state.chartWidth) > 1) {
                this.state.chartWidth = width;
            }
        };
        onMounted(() => {
            resize();
            if (typeof ResizeObserver !== "undefined") {
                observer = new ResizeObserver(resize);
                observer.observe(this.chartRef.el);
            } else {
                window.addEventListener("resize", resize);
            }
        });
        onWillUnmount(() => {
            if (observer) observer.disconnect();
            else window.removeEventListener("resize", resize);
        });
    }
    isHidden(i) { return this.state.hidden.includes(i); }
    toggleHidden(i) {
        this.state.hidden = this.isHidden(i)
            ? this.state.hidden.filter((x) => x !== i)
            : [...this.state.hidden, i];
    }
    get legendItems() {
        return this.series.map((s, i) => ({
            label: s.label, index: i, color: this.color(i), hidden: this.isHidden(i) }));
    }

    get type() {
        return this.props.payload.type || "bar";
    }
    get display() {
        return (this.props.meta && this.props.meta.display) || {};
    }
    get horizontal() {
        return this.type === "hbar";
    }
    get stacked() {
        return this.type === "column" || !!this.display.stacked;
    }
    get showGrid() {
        return this.display.show_grid !== false;
    }
    get showLegend() {
        return this.display.show_legend !== false;
    }
    get smooth() {
        return !!this.display.smooth;
    }
    get isLine() {
        return this.type === "line" || this.type === "area";
    }
    get goalValue() {
        return this.display.goal_value || 0;
    }
    get comboOn() {
        return !!this.display.combo_line && !this.isLine && !this.horizontal;
    }
    get allLabels() {
        return this.props.payload.labels || [];
    }
    get allSeries() {
        return this.props.payload.series || [];
    }
    get visibleRange() {
        const total = this.allLabels.length;
        const size = this.state.zoomSize
            ? Math.max(1, Math.min(this.state.zoomSize, total)) : total;
        const start = Math.max(0, Math.min(this.state.zoomStart, Math.max(0, total - size)));
        return { start, end: start + size, size, total };
    }
    get labels() {
        const range = this.visibleRange;
        return this.allLabels.slice(range.start, range.end);
    }
    get series() {
        const range = this.visibleRange;
        return this.allSeries.map((series) => ({
            ...series, data: (series.data || []).slice(range.start, range.end),
        }));
    }
    get targetSeries() {
        const target = this.props.payload.target_series;
        if (!target || !Array.isArray(target.data)) return null;
        const range = this.visibleRange;
        return { ...target, data: target.data.slice(range.start, range.end) };
    }
    get hasZoom() { return this.allLabels.length > 8; }
    get zoomLabel() {
        const range = this.visibleRange;
        return `${range.start + 1}–${range.end} / ${range.total}`;
    }
    zoomIn() {
        const range = this.visibleRange;
        if (range.total <= 4) return;
        const size = Math.max(4, Math.floor(range.size * 0.7));
        this.state.zoomSize = size;
        this.state.zoomStart = Math.max(0, range.start + Math.floor((range.size - size) / 2));
    }
    zoomOut() {
        const range = this.visibleRange;
        const size = Math.min(range.total, Math.ceil(range.size / 0.7));
        this.state.zoomSize = size === range.total ? 0 : size;
        this.state.zoomStart = Math.max(0, range.start - Math.floor((size - range.size) / 2));
    }
    resetZoom() { this.state.zoomStart = 0; this.state.zoomSize = 0; }
    pan(direction) {
        const range = this.visibleRange;
        if (range.size >= range.total) return;
        const step = Math.max(1, Math.floor(range.size * 0.35));
        this.state.zoomStart = Math.max(
            0, Math.min(range.total - range.size, range.start + direction * step));
    }
    onWheel(ev) {
        if (!this.hasZoom || (!ev.ctrlKey && !ev.metaKey)) return;
        ev.preventDefault();
        if (ev.deltaY < 0) this.zoomIn();
        else this.zoomOut();
    }
    color(seriesIndex, categoryIndex = null, naturalIndex = null) {
        return chartColor(this.props.meta, seriesIndex, categoryIndex, naturalIndex);
    }

    get pad() {
        // Horizontal bars hold long category NAMES in the left gutter and value
        // labels past the right end, so both sides need more room than a vertical
        // chart where the left gutter only holds short axis numbers.
        // A combo line rides a secondary axis on the right, so widen that gutter.
        const rightExtra = this.hasComboLines ? 30 : 0;
        if (this.horizontal) {
            const category = this.categoryGutter;
            return { top: 16, bottom: 34,
                left: this.rtl ? 46 : category, right: this.rtl ? category : 46 };
        }
        return { top: 16, right: 16 + rightExtra,
            bottom: this.rotateCategoryLabels ? 92 : 40, left: 48 };
    }

    get chartWidth() {
        return this.horizontal ? Math.max(240, this.state.chartWidth || W) : W;
    }

    get categoryGutter() {
        return this.horizontalLayout.gutter;
    }

    get horizontalLayout() {
        const labels = this.labels;
        const width = this.chartWidth;
        const key = JSON.stringify([width, labels]);
        if (this._horizontalLayout && this._horizontalLayout.key === key) return this._horizontalLayout;
        const longest = labels.reduce((max, label) => Math.max(max, categoryLabelWidth(label)), 0);
        // Preserve useful plotting room even in a narrow tile. Wider tiles give
        // labels more space automatically, instead of scaling a fixed 16-char cap.
        const gutter = Math.min(Math.max(70, longest + 18), width * 0.45, width - 166);
        const lines = labels.map((label) => wrapCategoryLabel(label, gutter - 18));
        const maxLines = lines.reduce((max, parts) => Math.max(max, parts.length), 1);
        const rowHeight = Math.max(28, maxLines * CATEGORY_LINE_HEIGHT + 10);
        this._horizontalLayout = { key, gutter, lines,
            height: Math.max(H, labels.length * rowHeight + 50) };
        return this._horizontalLayout;
    }

    get horizontalLabelLines() {
        return this.horizontalLayout.lines;
    }

    get chartHeight() {
        if (!this.horizontal) return H;
        // Dense charts scroll inside the tile. Every category remains visible
        // and multiline labels never overlap the next bar, including in export.
        return this.horizontalLayout.height;
    }

    get svgStyle() {
        return this.horizontal ? `height: ${this.chartHeight}px; min-height: ${this.chartHeight}px;` : "";
    }

    /**
     * Rotate only category axes that would otherwise collide.  This is shared
     * by bar, column, line, area, stacked and combo charts.  Horizontal bars
     * already have a dedicated name gutter; numeric scatter axes live in a
     * different component and must never inherit category-label rotation.
     *
     * Text measurement is deliberately deterministic: SVG getBBox() is not
     * available during OWL render or headless SSR.  6.2 px is the conservative
     * average glyph width of the 11 px DM Sans axis font.
     */
    get rotateCategoryLabels() {
        if (this.horizontal || this.labels.length < 2) return false;
        const n = this.labels.length;
        const maxTicks = 12;
        const stride = n > maxTicks ? Math.ceil(n / maxTicks) : 1;
        const slot = ((W - 48 - 16) / n) * stride;
        const longest = this.labels.reduce(
            (max, label) => Math.max(max, String(label == null ? "" : label).length), 0);
        const renderedChars = Math.min(longest, 22);
        return renderedChars > 10 || renderedChars * 6.2 > slot * 0.82;
    }

    get categoryLabelAngle() {
        if (!this.rotateCategoryLabels) return 0;
        return this.rtl ? CROWDED_CATEGORY_ANGLE : -CROWDED_CATEGORY_ANGLE;
    }

    get plot() {
        const PAD = this.pad;
        return {
            x: PAD.left, y: PAD.top,
            w: this.chartWidth - PAD.left - PAD.right,
            h: this.chartHeight - PAD.top - PAD.bottom,
        };
    }

    /** Value-axis extent across all series (stacked sums when stacking). */
    get valueScale() {
        let max = 0, min = 0;
        if (this.stacked) {
            // Track the running cumulative height/depth per category, exactly as
            // the bars stack, so a category mixing positive and negative values
            // keeps its true extent (a net sum would collapse the axis and push
            // the bars outside the plot).
            this.labels.forEach((_, i) => {
                let run = 0;
                this.series.forEach((s, si) => {
                    if (this.isHidden(si) || (this.hasComboLines && s.as_line)) return;
                    run += s.data[i] || 0;
                    max = Math.max(max, run);
                    min = Math.min(min, run);
                });
            });
        } else {
            this.series.forEach((s, si) => {
                // as_line series ride the secondary (line) axis, not this one -
                // but only when the combo actually applies (upright bar chart).
                if (this.isHidden(si) || (this.hasComboLines && s.as_line)) return;
                for (const v of s.data) {
                    max = Math.max(max, v || 0);
                    min = Math.min(min, v || 0);
                }
            });
        }
        // Keep the goal line and the cumulative curve inside the plot.
        if (this.goalValue) max = Math.max(max, this.goalValue);
        if (this.targetSeries) {
            for (const value of this.targetSeries.data) {
                max = Math.max(max, value || 0);
                min = Math.min(min, value || 0);
            }
        }
        if (this.comboOn && this.series[0]) {
            let run = 0;
            for (const v of this.series[0].data) run += v || 0;
            max = Math.max(max, run);
        }
        return niceScale(min, max, 5);
    }

    valueToPx(v) {
        const sc = this.valueScale;
        const ratio = (v - sc.min) / (sc.max - sc.min || 1);
        if (this.horizontal) {
            // RTL: the value axis is on the right and bars grow leftward.
            return this.rtl
                ? this.plot.x + this.plot.w - ratio * this.plot.w
                : this.plot.x + ratio * this.plot.w;
        }
        return this.plot.y + this.plot.h - ratio * this.plot.h;
    }

    get gridLines() {
        const sc = this.valueScale;
        return sc.ticks.map((t) => ({
            value: t,
            label: this.fmt(t, this.series[0]),
            pos: this.valueToPx(t),
        }));
    }

    get rtl() {
        const el = typeof document !== "undefined" && document.documentElement;
        return !!(el && (el.dir === "rtl" || document.dir === "rtl"));
    }

    /** One band per category on the category axis. */
    get bands() {
        const n = this.labels.length || 1;
        const size = (this.horizontal ? this.plot.h : this.plot.w) / n;
        // A vertical axis crowds long names; a horizontal axis has a wider gutter.
        const cap = this.rotateCategoryLabels ? 22 : 13;
        // Thin the axis labels when a series is dense (e.g. 18 months of data),
        // so ticks never overlap into an unreadable smear. The full label is
        // always in the tooltip; only the printed tick is skipped.
        const maxTicks = this.horizontal ? n : (this.rotateCategoryLabels ? 12 : 8);
        const stride = n > maxTicks ? Math.ceil(n / maxTicks) : 1;
        // In an RTL locale the horizontal category axis reads right-to-left; the
        // value axis stays LTR (numbers are latin), so only reverse the columns.
        const mirror = this.rtl && !this.horizontal;
        const horizontalLines = this.horizontal ? this.horizontalLabelLines : null;
        return this.labels.map((label, i) => {
            const s = String(label == null ? "" : label);
            const tick = this.horizontal || s.length <= cap ? s : s.slice(0, cap - 1) + "…";
            const tickLines = horizontalLines ? horizontalLines[i] : [tick];
            const idx = mirror ? (n - 1 - i) : i;
            const start = (this.horizontal ? this.plot.y : this.plot.x) + idx * size;
            const center = start + size / 2;
            const tickX = this.horizontal
                ? (this.rtl ? this.plot.x + this.plot.w + 6 : this.plot.x - 6)
                : center;
            const tickY = this.horizontal
                ? center + 3 - (tickLines.length - 1) * CATEGORY_LINE_HEIGHT / 2
                : this.plot.y + this.plot.h + (this.rotateCategoryLabels ? 12 : 26);
            return {
                label,   // full text -> tooltip
                tick,
                tickLines,
                showTick: i % stride === 0,   // thin dense axes to avoid overlap
                index: i,
                sourceIndex: this.visibleRange.start + i,
                start,
                size,
                tickX,
                tickY,
                tickDirection: this.horizontal ? (this.rtl ? "rtl" : "ltr") : null,
                tickAnchor: this.horizontal
                    ? "end"
                    : (this.rotateCategoryLabels ? (this.rtl ? "start" : "end") : "middle"),
                tickTransform: this.rotateCategoryLabels
                    ? `rotate(${this.categoryLabelAngle} ${tickX} ${tickY})`
                    : null,
            };
        });
    }

    /** Bar rectangles: grouped, or stacked when type === column. */
    get bars() {
        if (this.isLine) return [];
        const out = [];
        const zero = this.valueToPx(0);
        // Visible bar series (non-hidden, not drawn as a line) drive the slot width.
        const visCount = this.series.filter(
            (s, si) => !this.isHidden(si) && !(this.hasComboLines && s.as_line)).length || 1;
        const groupCount = this.stacked ? 1 : visCount;
        this.bands.forEach((band) => {
            const inner = band.size * 0.7;
            const slot = inner / groupCount;
            let stackBase = 0;
            let vi = 0;   // visible index, so hidden series leave no gap
            this.series.forEach((s, si) => {
                // Skip a series only when it is actually drawn as a combo overlay
                // line (upright bar); on horizontal it stays a normal bar.
                if (this.isHidden(si) || (this.hasComboLines && s.as_line)) return;
                const v = s.data[band.index] || 0;
                const color = this.color(si, band.index, si);
                const common = { color, value: v, label: band.label,
                    seriesLabel: s.label, series: s, index: band.sourceIndex };
                if (this.horizontal) {
                    const x = Math.min(zero, this.valueToPx(v));
                    const len = Math.abs(this.valueToPx(v) - zero);
                    out.push({
                        ...common, x, y: band.start + band.size * 0.15 + vi * slot,
                        w: len, h: slot * 0.9,
                    });
                } else if (this.stacked) {
                    const top = this.valueToPx(stackBase + v);
                    const bottom = this.valueToPx(stackBase);
                    out.push({
                        ...common, x: band.start + band.size * 0.15, y: Math.min(top, bottom),
                        w: inner, h: Math.abs(bottom - top),
                    });
                    stackBase += v;
                } else {
                    const top = this.valueToPx(v);
                    out.push({
                        ...common, x: band.start + band.size * 0.15 + vi * slot,
                        y: Math.min(zero, top), w: slot * 0.9,
                        h: Math.abs(top - zero),
                    });
                }
                vi++;
            });
        });
        return out;
    }

    /** Line/area paths, one per series. */
    get lines() {
        if (!this.isLine) return [];
        const fill = this.type === "area";
        return this.series.map((s, si) => {
            if (this.isHidden(si)) return null;
            const pts = this.bands.map((band) => ({
                x: band.start + band.size / 2,
                y: this.valueToPx(s.data[band.index] || 0),
            }));
            let area = "";
            if (fill && pts.length) {
                const base = this.valueToPx(0);
                area = linePath(pts)
                    + ` L${pts[pts.length - 1].x.toFixed(2)},${base.toFixed(2)}`
                    + ` L${pts[0].x.toFixed(2)},${base.toFixed(2)} Z`;
            }
            const path = this.smooth ? smoothPath(pts) : linePath(pts);
            return { path, area, color: this.color(si), points: pts, series: s,
                comparison: !!s.comparison };
        }).filter(Boolean);
    }

    /** True when any visible series is flagged to draw as a combo line overlay.
     *  Combo lines ride a secondary VERTICAL axis, so they only apply to an
     *  upright bar chart; on a horizontal bar an as_line series stays a bar. */
    get hasComboLines() {
        return !this.isLine && !this.horizontal
            && this.series.some((s, si) => s.as_line && !this.isHidden(si));
    }

    /** Secondary value axis, scaled only over the as_line (combo) series so a
     *  small-magnitude line (e.g. a % rate) still reads over large $ bars. */
    get lineScale() {
        let max = 0, min = 0;
        this.series.forEach((s, si) => {
            if (!s.as_line || this.isHidden(si)) return;
            for (const v of s.data) {
                max = Math.max(max, v || 0);
                min = Math.min(min, v || 0);
            }
        });
        return niceScale(min, max, 5);
    }

    lineToPx(v) {
        const sc = this.lineScale;
        const ratio = (v - sc.min) / (sc.max - sc.min || 1);
        // Combo lines are only drawn on vertical (non-horizontal) charts.
        return this.plot.y + this.plot.h - ratio * this.plot.h;
    }

    /** Combo overlay: as_line series drawn as lines on their own axis. */
    get overlayLines() {
        if (!this.hasComboLines) return [];
        return this.series.map((s, si) => {
            if (!s.as_line || this.isHidden(si)) return null;
            const pts = this.bands.map((band) => ({
                x: band.start + band.size / 2,
                y: this.lineToPx(s.data[band.index] || 0),
            }));
            const path = this.smooth ? smoothPath(pts) : linePath(pts);
            return { path, color: this.color(si), points: pts, label: s.label, si, series: s };
        }).filter(Boolean);
    }

    /** Right-hand tick labels for the secondary (combo line) axis. */
    get lineTicks() {
        if (!this.hasComboLines) return [];
        return this.lineScale.ticks.map((v) => ({
            pos: this.lineToPx(v), label: this.fmt(v, this.series.find((s) => s.as_line)),
        }));
    }

    /** Horizontal goal line at the target value (vertical bar / line charts). */
    get goalLine() {
        if (!this.goalValue || this.horizontal) return null;
        const y = this.valueToPx(this.goalValue);
        return { y, x1: this.plot.x, x2: this.plot.x + this.plot.w,
                 label: this.fmt(this.goalValue, this.series[0]) };
    }

    /** Date-effective target trajectory; supports upright and horizontal charts. */
    get targetPath() {
        const target = this.targetSeries;
        if (!target || !target.data.length) return null;
        const points = this.bands.map((band) => this.horizontal
            ? { x: this.valueToPx(target.data[band.index] || 0),
                y: band.start + band.size / 2 }
            : { x: band.start + band.size / 2,
                y: this.valueToPx(target.data[band.index] || 0) });
        const last = points[points.length - 1];
        return {
            path: linePath(points), points, last,
            label: target.label || _t("Target"),
            value: target.data[target.data.length - 1] || 0,
            series: target,
        };
    }

    /** Cumulative running-total overlay of the first series (Pareto). */
    get cumulativePath() {
        if (!this.comboOn || !this.series[0]) return null;
        let run = 0;
        const pts = this.bands.map((band) => {
            run += this.series[0].data[band.index] || 0;
            return { x: band.start + band.size / 2, y: this.valueToPx(run) };
        });
        return { path: linePath(pts), points: pts };
    }

    get viewBox() {
        return `0 0 ${this.chartWidth} ${this.chartHeight}`;
    }

    fmt(v, series = null) {
        const payload = this.props.payload;
        return formatValue(
            v,
            (series && series.number_format) || payload.number_format,
            (series && series.currency) || payload.currency,
            (series && series.unit) || payload.unit || ""
        );
    }

    /** Show value labels only when enabled and the chart is not too dense. */
    get showValues() {
        return this.display.show_values !== false && !this.isLine && this.bars.length <= 16;
    }

    /** Text-label position for a bar's value. */
    valueLabel(bar) {
        if (this.horizontal) {
            const leftward = this.rtl ? bar.value >= 0 : bar.value < 0;
            // Negative values grow towards the category gutter. Put their
            // values just inside that end so they cannot cover category names.
            if (bar.value < 0) {
                return { x: leftward ? bar.x + 4 : bar.x + bar.w - 4,
                    y: bar.y + bar.h / 2 + 3, anchor: leftward ? "start" : "end" };
            }
            return { x: leftward ? bar.x - 4 : bar.x + bar.w + 4,
                y: bar.y + bar.h / 2 + 3, anchor: leftward ? "end" : "start" };
        }
        return { x: bar.x + bar.w / 2, y: Math.max(bar.y - 5, 10), anchor: "middle" };
    }

    onBarClick(bar) {
        // Comparison marks represent a shifted time window. Until a point-level
        // prior-period domain is available, keep them inspectable by tooltip but
        // never open today's records under yesterday's bar.
        if (bar.series && bar.series.comparison) return;
        if (this.props.onDrill) {
            this.props.onDrill({ label: bar.label, index: bar.index });
        }
    }
    onBandClick(band) {
        if (this.props.onDrill) {
            this.props.onDrill({ label: band.label, index: band.sourceIndex });
        }
    }

    // -- tooltip ------------------------------------------------------------
    onBarHover(ev, bar) {
        showTooltip(ev, bar.label, [{ label: bar.seriesLabel || _t("Value"), value: this.fmt(bar.value, bar.series), color: bar.color }]);
    }
    onBandHover(ev, band) {
        const rows = this.series.map((s, si) => ({
            label: s.label, value: this.fmt(s.data[band.index] || 0, s),
            color: this.color(si, band.index, si),
        }));
        showTooltip(ev, band.label, rows);
    }
    onMove(ev) {
        moveTooltip(ev);
    }
    onLeave() {
        hideTooltip();
    }
}
