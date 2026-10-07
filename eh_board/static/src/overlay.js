/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * One app-level overlay host for the board's anchored popovers.
 *
 * WHY. A popover written as `position: absolute` beside its trigger is destroyed
 * by any scrolling ancestor. Per CSS Overflow 3, a box whose `overflow-x` is
 * `auto` computes `overflow-y: auto` too, so the header command bar is a scroll
 * container on BOTH axes and clips to its ~48px padding box; an ancestor's clip
 * reaches an out-of-flow box whenever that ancestor sits between the box and its
 * containing block (CSS 2.1 11.1.1). The export dropdown was anchored to a
 * `position: relative` wrapper inside that bar, so it rendered in full and was
 * cut to a 2px sliver, unreachable by the mouse and with no JS error.
 *
 * HOW. `.eh_board_overlay` is `position: fixed; inset: 0`, so its containing
 * block is the viewport (or the nearest transformed/filtered ancestor) and none
 * of the board's scroll containers can clip what it holds. It stays a DOM child
 * of `.eh_board_app`, so the design tokens and every app-scoped rule (focus
 * ring, RTL, kiosk, print) keep applying to the popovers inside it. Odoo ships
 * the same shape: spreadsheet portals its popovers to the `.o-spreadsheet` root.
 *
 * RULE FOR FUTURE POPOVERS: never anchor one inside the header, the command bar,
 * the sub-nav, a widget cell or a builder column. Portal it here and place it
 * with `useBoardPopover`.
 */

import { onMounted, onPatched, useExternalListener, useRef } from "@odoo/owl";

let SEQ = 0;

/** Per-instance host id, so the portal's document.querySelector can never
 *  resolve to another board mounted in the same document. */
export function newOverlayId() {
    SEQ += 1;
    return `eh_board_overlay_${SEQ}`;
}

/**
 * Measure the host's own coordinate space.
 *
 * The host is `position: fixed`, so normally one host pixel is one viewport
 * pixel. That stops being true the moment any ancestor carries a transform,
 * filter or backdrop-filter: the ancestor then becomes the host's containing
 * block, and a scaling transform also scales the offsets we write. Rather than
 * assume, park a probe at two known offsets and read back where they land; that
 * inverts any translate+scale exactly, with no dependency on which ancestor did
 * it. (The board's own header carries `backdrop-filter: blur(14px)`, which in
 * Chromium does establish a containing block for fixed descendants - measured -
 * so this is not a hypothetical.)
 *
 * @param {HTMLElement} pop  the popover itself, used as its own probe so the
 *                           measurement includes any style that applies to it
 * @returns {{x: number, y: number, sx: number, sy: number}} host origin in
 *          viewport px and the host-px -> viewport-px scale
 */
function calibrate(pop) {
    const read = (left, top) => {
        pop.style.left = `${left}px`;
        pop.style.top = `${top}px`;
        return pop.getBoundingClientRect();
    };
    const b = read(100, 100);
    // Park the box back at the origin and read there LAST, so the caller's
    // measurements are taken at the widest position available to it. The box is
    // shrink-to-fit with `right: auto`, so a box left parked at 100px would
    // measure 100px narrower than it ends up (and taller, from the wrapping)
    // on any viewport narrower than its natural width plus 100.
    const a = read(0, 0);
    const sx = (b.left - a.left) / 100;
    const sy = (b.top - a.top) / 100;
    // The popover's OWN transform is in every rect we just read. It is constant
    // for a resting popover and cancels out, but the entry animation
    // (eh_board_pop, translateY(-4px) -> 0) is not constant: a re-render landing
    // mid-animation would measure the moving box and leave the popover parked a
    // few px off once the animation settles. Measure the resting geometry.
    const own = ownTranslate(pop);
    return {
        x: a.left - own.x,
        y: a.top - own.y,
        sx: Number.isFinite(sx) && sx > 0 ? sx : 1,
        sy: Number.isFinite(sy) && sy > 0 ? sy : 1,
    };
}

/** The element's own transform translation, or zero when it has none. */
function ownTranslate(el) {
    const value = getComputedStyle(el).transform;
    if (!value || value === "none") {
        return { x: 0, y: 0 };
    }
    try {
        const matrix = new DOMMatrixReadOnly(value);
        return { x: matrix.m41, y: matrix.m42 };
    } catch {
        return { x: 0, y: 0 };
    }
}

/**
 * Place a mounted popover under its anchor, writing the offsets in the overlay
 * host's own coordinate space.
 *
 * Always leaves the popover visible: the stylesheet hides it until `.o_placed`
 * so there is no first-frame flash at the host origin, so a throw in here must
 * never be able to hide the control for good.
 *
 * @param {HTMLElement} pop     the popover, a child of the overlay host
 * @param {HTMLElement} anchor  the control it belongs to
 * @param {Object}  [options]
 * @param {number}  [options.gap=6]         px between anchor and popover
 * @param {string}  [options.align="end"]   "end" aligns the popover's trailing
 *        edge to the anchor's trailing edge (right in LTR, left in RTL)
 * @param {number}  [options.pad=8]         px kept clear of the viewport edges
 * @param {number}  [options.minHeight=140] never cap shorter than this
 */
export function placePopover(pop, anchor, options = {}) {
    const { gap = 6, align = "end", pad = 8, minHeight = 140 } = options;
    // Clearing the cap below un-overflows the box, and the browser then clamps
    // its scroll offset to zero. Without this the popover snaps back to the top
    // on every wheel tick once it is capped, which puts its lower items out of
    // reach: the very failure this whole change exists to remove.
    const scrollTop = pop.scrollTop;
    try {
        // Measure against the stylesheet's own cap, not last frame's override.
        pop.style.maxHeight = "";
        // rtlcss rewrites the stylesheet's physical `left` to `right` in the RTL
        // bundle; clear both cross offsets so the box is never over-constrained.
        pop.style.right = "auto";
        pop.style.bottom = "auto";
        const frame = calibrate(pop);
        const aRect = anchor.getBoundingClientRect();
        const rtl = getComputedStyle(anchor).direction === "rtl";
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        // Height first. Capping can add a scrollbar gutter, and a gutter widens
        // a shrink-to-fit box, so the width that positions it has to be read
        // after the cap is applied.
        const height = pop.getBoundingClientRect().height;
        const below = vh - pad - (aRect.bottom + gap);
        const above = aRect.top - gap - pad;
        let y;
        if (height <= below || below >= above) {
            const cap = Math.max(minHeight, below);
            if (height > below) {
                pop.style.maxHeight = `${cap / frame.sy}px`;
            }
            // minHeight can force a cap taller than the space below the anchor.
            // Slide up to keep the box on screen rather than hang off the edge.
            y = Math.min(aRect.bottom + gap,
                         Math.max(pad, vh - pad - Math.min(height, cap)));
        } else {
            // No room below and more above: open upwards rather than cover the
            // control the user just clicked.
            const cap = Math.max(minHeight, above);
            if (height > above) {
                pop.style.maxHeight = `${cap / frame.sy}px`;
            }
            y = Math.max(pad, aRect.top - gap - Math.min(height, cap));
        }

        const width = pop.getBoundingClientRect().width;
        let x = (align === "end") !== rtl ? aRect.right - width : aRect.left;
        x = Math.max(pad, Math.min(x, vw - width - pad));

        pop.style.left = `${(x - frame.x) / frame.sx}px`;
        pop.style.top = `${(y - frame.y) / frame.sy}px`;
        // After the cap is back on, so the browser re-clamps it for us.
        pop.scrollTop = scrollTop;
    } finally {
        // Visible even if the measurement above threw: an unplaced popover at
        // the host origin is recoverable, an invisible one is not.
        pop.classList.add("o_placed");
    }
}

/**
 * Keep one portalled popover glued to its anchor for as long as it is open.
 * Safe for a popover that is closed most of the time: every callback returns
 * immediately until both nodes exist.
 *
 * @param {string} popRef     t-ref on the portalled popover
 * @param {string} anchorRef  t-ref on the control it hangs from
 * @param {Object} [options]  forwarded to placePopover; `selector` is a
 *                            last-resort lookup if a t-ref ever fails to cross
 *                            the portal on some future OWL build
 */
export function useBoardPopover(popRef, anchorRef, options = {}) {
    const pop = useRef(popRef);
    const anchor = useRef(anchorRef);
    const el = () =>
        pop.el || (options.selector ? document.querySelector(options.selector) : null);
    const place = (ev) => {
        const node = el();
        // A scroll inside the popover cannot move the anchor, and re-placing on
        // it would only cost a forced layout per wheel tick.
        if (!node || !anchor.el || (ev && ev.target === node)) {
            return;
        }
        placePopover(node, anchor.el, options);
    };
    // The popover renders into the overlay host, which sits at the top of the
    // app, so it is no longer the toggle's neighbour in tab order. Move focus in
    // when it opens and hand it back when it closes, or a keyboard user tabs
    // past a menu they just opened. These hooks belong to the OWNING component,
    // so they fire on every render: act on the open/close transition only, and
    // never from the resize/scroll listeners, which would steal focus.
    let open = false;
    let movedFocus = false;
    const sync = () => {
        const node = el();
        if (node && anchor.el) {
            place();
            if (!open) {
                open = true;
                const first = node.querySelector("button:not([disabled])");
                movedFocus = !!first;
                if (first) {
                    first.focus();
                }
            }
        } else if (open) {
            open = false;
            // Only when the popover still held focus: its removal leaves the
            // document body focused, and anything else means the user has
            // deliberately moved on.
            if (movedFocus && anchor.el
                && (!document.activeElement || document.activeElement === document.body)) {
                anchor.el.focus();
            }
            movedFocus = false;
        }
    };
    onMounted(sync);
    onPatched(sync);
    useExternalListener(window, "resize", place);
    // Capture phase: a scroll inside the command bar does not bubble to window,
    // and that bar really does scroll horizontally on narrow viewports.
    useExternalListener(window, "scroll", place, { capture: true });
    return {
        pop,
        anchor,
        place,
        /** For outside-click guards: the trigger wrapper no longer contains the
         *  popover, so both have to be consulted. */
        contains(node) {
            const own = el();
            return !!(own && node && own.contains(node));
        },
    };
}
