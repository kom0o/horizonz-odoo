/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour: presentation mode loads a LAZY, below-the-fold widget.
 * The seed board parks the scatter as the last widget (index 10, past the
 * 8-eager cutoff) at y=40, far below the fold, so it is deferred and was never
 * scrolled into view. Pressing Play and jumping to its slide must FETCH +
 * render it, not leave a stuck loading skeleton (the bug this guards: a blank
 * scatter in the slideshow). */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_present_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        // enter the presentation slideshow
        { trigger: ".eh_board_playbtn", run: "click" },
        { trigger: ".eh_board_present", run: () => {} },
        // jump to the last slide = the scatter (lazy, below the fold)
        { trigger: ".eh_board_present_dots .eh_board_present_dot:last-child", run: "click" },
        // the deferred widget must resolve (fetch + render), NOT sit on a
        // loading skeleton forever - data-agnostic proof the lazy fetch fires.
        { trigger: ".eh_board_present_slide .eh_board_widget[data-item-type=scatter]:not(:has(.eh_board_widget_skel))", run: () => {} },
        // the slicer (12th) renders its chips, not a false "No data" empty state
        // (control-category payload carries no labels/series).
        { trigger: ".eh_board_present_dots .eh_board_present_dot:nth-child(12)", run: "click" },
        { trigger: ".eh_board_present_slide .eh_board_widget[data-item-type=slicer] .eh_board_slicer_chip", run: () => {} },
        // the decomposition tree (13th) renders its root node, not "No data"
        // (its data lives in level0.nodes, not labels/series).
        { trigger: ".eh_board_present_dots .eh_board_present_dot:nth-child(13)", run: "click" },
        {
            trigger: ".eh_board_present_slide .eh_board_widget[data-item-type=decomp] .eh_board_decomp_root",
            run: () => {},
        },
    ],
});
