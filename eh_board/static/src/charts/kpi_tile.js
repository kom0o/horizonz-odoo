/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Rich KPI / tile: an icon badge, a big tabular-figure number, a trend badge
 * (period-over-period), a live sparkline, and a target progress bar - the
 * "alive" tile a buyer expects, not a bare number. */

import { uiText } from "../ui_text";

import { Component } from "@odoo/owl";
import { contrastSafeColor, formatValue, linePath } from "./svg_util";
import { matchRule, textOn } from "../conditional";

export class KpiTile extends Component {
    static template = "eh_board.KpiTile";
    uiText = uiText;
    static props = {
        payload: Object,
        meta: { type: Object, optional: true },
        onDrill: { type: Function, optional: true },
    };

    get accent() {
        return (this.props.meta && this.props.meta.accent) || "mint";
    }
    get tileStyle() {
        return (this.props.meta && this.props.meta.tile_style) || "soft";
    }
    get icon() {
        return (this.props.meta && this.props.meta.icon) || "fa-hashtag";
    }
    get label() {
        return this.props.payload.subtitle || (this.props.meta && this.props.meta.title) || "";
    }
    get value() {
        return this.props.payload.value || 0;
    }
    get display() {
        const p = this.props.payload;
        return formatValue(this.value, p.number_format, p.currency, p.unit || "");
    }
    get isKpi() {
        return (this.props.payload.type || "tile") === "kpi";
    }

    // -- conditional formatting --------------------------------------------
    get cond() {
        const rules = (this.props.meta && this.props.meta.conditional_rules) || [];
        // A KPI shows its primary measure - index 0.
        return matchRule(rules, this.value, 0);
    }
    get valueStyle() {
        const color = this.cond && this.cond.style === "text" ? this.cond.color : "";
        return /^#[0-9a-f]{6}$/i.test(color)
            ? `--eh-cond-accent:${contrastSafeColor(color)};` : "";
    }
    get hasTextCondition() {
        return !!this.valueStyle;
    }
    get fillStyle() {
        // A "fill" (or "bar", which has no meaning on a single value) rule
        // repaints the whole tile; text on it stays readable.
        if (this.cond && (this.cond.style === "fill" || this.cond.style === "bar")) {
            return `background:${this.cond.color};color:${textOn(this.cond.color)};`;
        }
        return "";
    }

    // -- click-through ------------------------------------------------------
    get clickable() {
        const m = this.props.meta;
        return !!(m && m.model && m.click_action !== "none" && this.props.onDrill);
    }
    onClick() {
        // Whole-widget click: open the exact records behind the tile (its own
        // static scope), respecting record rules.
        if (this.clickable) this.props.onDrill({});
    }

    // -- trend --------------------------------------------------------------
    get hasTrend() {
        return this.props.payload.trend !== undefined && this.props.payload.trend !== null;
    }
    get trendPct() {
        return Math.abs(Math.round((this.props.payload.trend || 0) * 100));
    }
    get trendUp() {
        return (this.props.payload.trend || 0) >= 0;
    }

    // -- sparkline ----------------------------------------------------------
    get spark() {
        const live = this.props.payload.spark || [];
        if (live.length > 2) return live;
        return (this.props.payload.history || []).map((point) => point.value);
    }
    get hasSpark() {
        return this.spark.length > 2;
    }
    get sparkPath() {
        const data = this.spark;
        if (data.length < 2) return "";
        const w = 120, h = 34;
        const min = Math.min(...data), max = Math.max(...data);
        const range = max - min || 1;
        const pts = data.map((v, i) => ({
            x: (i / (data.length - 1)) * w,
            y: h - ((v - min) / range) * (h - 4) - 2,
        }));
        return linePath(pts);
    }
    get sparkArea() {
        const p = this.sparkPath;
        if (!p) return "";
        return `${p} L120,34 L0,34 Z`;
    }

    // -- target -------------------------------------------------------------
    get hasTarget() {
        return this.props.payload.target !== undefined;
    }
    get achievement() {
        return Math.round((this.props.payload.achievement || 0) * 100);
    }
    get progressWidth() {
        return Math.max(0, Math.min(100, this.achievement));
    }
    get targetDisplay() {
        const p = this.props.payload;
        return formatValue(p.target || 0, p.number_format, p.currency, p.unit || "");
    }
}

export class GaugeChart extends Component {
    static template = "eh_board.GaugeChart";
    uiText = uiText;
    static props = {
        payload: Object,
        meta: { type: Object, optional: true },
        onDrill: { type: Function, optional: true },
    };

    get accent() {
        return (this.props.meta && this.props.meta.accent) || "mint";
    }
    get clickable() {
        const m = this.props.meta;
        return !!(m && m.model && m.click_action !== "none" && this.props.onDrill);
    }
    onClick() {
        if (this.clickable) this.props.onDrill({});
    }
    get value() {
        return this.props.payload.value || 0;
    }
    get target() {
        return this.props.payload.target || 0;
    }
    get ratio() {
        return Math.max(0, Math.min(1, this.target ? this.value / this.target : 0));
    }
    get arc() {
        const cx = 120, cy = 120, r = 92;
        const a0 = Math.PI;
        const a1 = Math.PI + this.ratio * Math.PI;
        const p = (a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
        const [x0, y0] = p(a0);
        const [x1, y1] = p(a1);
        const large = this.ratio > 0.5 ? 1 : 0;
        const [bx, by] = p(2 * Math.PI);
        return {
            track: `M${x0},${y0} A${r},${r} 0 1 1 ${bx},${by}`,
            value: `M${x0},${y0} A${r},${r} 0 ${large} 1 ${x1},${y1}`,
        };
    }
    get display() {
        const p = this.props.payload;
        return formatValue(this.value, p.number_format, p.currency, p.unit || "");
    }
    get pct() {
        // The arc clamps (ratio), but the text must show TRUE achievement so
        // 250% of target reads "250%", not "100%".
        return this.target ? Math.round((this.value / this.target) * 100) : 0;
    }
    get targetDisplay() {
        const p = this.props.payload;
        return formatValue(this.target, p.number_format, p.currency, p.unit || "");
    }
}
