/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Original 12-column grid with pointer drag, edge resize and collision
 * push-down. No gridstack, no interact.js, no jQuery - just pointer events,
 * so the bundle stays clean and CSP-safe. */

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";

const COLS = 12;
const ROW_H = 40;   // px per grid row
const GAP = 12;     // px gap between cells

export class BoardGrid extends Component {
    static template = "eh_board.BoardGrid";
    static props = {
        items: Array,                 // [meta]
        payloads: Object,             // {id: payload}
        grid: Object,                 // {id: {x,y,w,h,minW,minH}}
        editMode: Boolean,
        loadingIds: { type: Object, optional: true },
        drillStacks: { type: Object, optional: true },
        crossFilters: { type: Array, optional: true },
        onLayoutChange: Function,
        onVisible: { type: Function, optional: true },
        onDrill: { type: Function, optional: true },
        onDrillUp: { type: Function, optional: true },
        onConfigure: { type: Function, optional: true },
        onRemove: { type: Function, optional: true },
        onDuplicate: { type: Function, optional: true },
        Item: Function,               // the BoardItem component
    };

    setup() {
        this.rootRef = useRef("grid");
        this.drag = useState({ id: null, mode: null });
        this._start = null;
        this._observer = null;
        onMounted(() => this._observeLazy());
        onWillUnmount(() => this._observer && this._observer.disconnect());
    }

    _observeLazy() {
        if (!this.props.onVisible || !this.rootRef.el || !window.IntersectionObserver) return;
        this._observer = new IntersectionObserver((entries) => {
            for (const e of entries) {
                if (e.isIntersecting) {
                    const id = parseInt(e.target.dataset.itemId, 10);
                    if (id) this.props.onVisible(id);
                    this._observer.unobserve(e.target);
                }
            }
        }, { rootMargin: "120px" });
        for (const cell of this.rootRef.el.querySelectorAll(".eh_board_cell[data-item-id]")) {
            this._observer.observe(cell);
        }
    }

    // -- geometry -----------------------------------------------------------
    _metrics() {
        // Read the live row height + gap from the grid so drag/resize track
        // whatever density is active (comfortable vs compact) with no coupling.
        const el = this.rootRef.el;
        if (!el) return { rowH: ROW_H, gap: GAP };
        const cs = getComputedStyle(el);
        const gap = parseFloat(cs.rowGap || cs.gap) || GAP;
        const rowH = parseFloat(cs.gridAutoRows) || ROW_H;
        return { rowH, gap };
    }
    cellWidth() {
        const el = this.rootRef.el;
        const w = el ? el.clientWidth : 1200;
        return (w - this._metrics().gap * (COLS - 1)) / COLS;
    }

    geom(meta) {
        const g = this.props.grid[meta.id] || meta.geometry || {};
        const base = {
            x: g.x ?? 0, y: g.y ?? 0,
            w: g.w ?? (meta.geometry ? meta.geometry.w : 4),
            h: g.h ?? (meta.geometry ? meta.geometry.h : 6),
            minW: meta.geometry ? meta.geometry.minW : 2,
            minH: meta.geometry ? meta.geometry.minH : 2,
        };
        if (this.drag.id === meta.id && this._preview) {
            return { ...base, ...this._preview };
        }
        return base;
    }

    itemStyle(meta) {
        const g = this.geom(meta);
        return `grid-column:${g.x + 1}/span ${g.w};grid-row:${g.y + 1}/span ${g.h};`;
    }

    itemProps(meta) {
        return {
            meta,
            payload: this.props.payloads[meta.id] || null,
            editMode: this.props.editMode,
            loading: !!(this.props.loadingIds && this.props.loadingIds[meta.id]),
            onDrill: (info) => this.props.onDrill && this.props.onDrill(meta, info),
            crossFilters: this.props.crossFilters || [],
            drillPath: (this.props.drillStacks && this.props.drillStacks[meta.id]) || [],
            onDrillUp: (level) => this.props.onDrillUp && this.props.onDrillUp(meta, level),
            onConfigure: () => this.props.onConfigure && this.props.onConfigure(meta),
            onRemove: () => this.props.onRemove && this.props.onRemove(meta),
            onDuplicate: () => this.props.onDuplicate && this.props.onDuplicate(meta),
        };
    }

    // -- interaction --------------------------------------------------------
    onDragStart(ev, meta, mode) {
        if (!this.props.editMode) return;
        ev.preventDefault();
        this.drag.id = meta.id;
        this.drag.mode = mode;
        const g = this.geom(meta);
        this._start = { px: ev.clientX, py: ev.clientY, g: { ...g } };
        this._preview = { ...g };
        const move = (e) => this.onDragMove(e, meta);
        const up = (e) => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            this.onDragEnd(meta);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    onDragMove(ev, meta) {
        if (!this._start) return;
        const { rowH, gap } = this._metrics();
        const cw = this.cellWidth() + gap;
        const ch = rowH + gap;
        // In RTL the grid columns flow right-to-left, so a rightward pointer move
        // must decrease the column index. Invert the horizontal delta.
        const dir = this.rootRef.el && getComputedStyle(this.rootRef.el).direction === "rtl" ? -1 : 1;
        const dx = dir * Math.round((ev.clientX - this._start.px) / cw);
        const dy = Math.round((ev.clientY - this._start.py) / ch);
        const s = this._start.g;
        if (this.drag.mode === "move") {
            this._preview = {
                x: Math.max(0, Math.min(COLS - s.w, s.x + dx)),
                y: Math.max(0, s.y + dy),
                w: s.w, h: s.h,
            };
        } else {
            this._preview = {
                x: s.x, y: s.y,
                w: Math.max(s.minW || 2, Math.min(COLS - s.x, s.w + dx)),
                h: Math.max(s.minH || 2, s.h + dy),
            };
        }
        this.render();
    }

    onDragEnd(meta) {
        if (this._preview) {
            const grid = { ...this.props.grid };
            grid[meta.id] = { ...(grid[meta.id] || {}), ...this.geom(meta), ...this._preview };
            const packed = this._compact(grid);
            this.props.onLayoutChange(packed);
        }
        this.drag.id = null;
        this.drag.mode = null;
        this._start = null;
        this._preview = null;
    }

    /** No-overlap pass: place items top-to-bottom, push colliders down. */
    _compact(grid) {
        const metas = this.props.items;
        const placed = [];
        const order = [...metas].sort((a, b) => {
            const ga = grid[a.id] || {}, gb = grid[b.id] || {};
            return (ga.y - gb.y) || (ga.x - gb.x);
        });
        const out = {};
        for (const meta of order) {
            const g = { ...(grid[meta.id] || this.geom(meta)) };
            let y = g.y;
            const overlaps = (yy) => placed.some((p) =>
                !(g.x + g.w <= p.x || p.x + p.w <= g.x || yy + g.h <= p.y || p.y + p.h <= yy));
            while (overlaps(y)) y += 1;
            g.y = y;
            placed.push({ x: g.x, y: g.y, w: g.w, h: g.h });
            out[meta.id] = g;
        }
        return out;
    }
}
