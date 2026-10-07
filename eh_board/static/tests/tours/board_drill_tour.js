/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour for in-canvas drill-down: click a bar on a drill-enabled
 * widget, it regroups a level deeper and shows a breadcrumb to climb back. */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_drill_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        // click a bar on the drill-enabled column widget
        { trigger: ".eh_board_widget[data-item-type=column] .eh_board_bar", run: "click" },
        // a breadcrumb appears with the drilled value as the last crumb
        { trigger: ".eh_board_widget[data-item-type=column] .eh_board_breadcrumb", run: () => {} },
        // Drill level uses long country names. Shared Cartesian renderer must
        // apply approved 65-degree collision-safe category-axis layout.
        {
            trigger: ".eh_board_widget[data-item-type=column] .eh_board_cat_label[transform^='rotate(-65']",
            run: () => {},
        },
        { trigger: ".eh_board_widget[data-item-type=column] .eh_board_crumb.o_last", run: () => {} },
        // climb back to the root level
        { trigger: ".eh_board_widget[data-item-type=column] .eh_board_crumb:not(.o_last)", run: "click" },
        {
            trigger: ".eh_board_widget[data-item-type=column]:not(:has(.eh_board_breadcrumb))",
            run: () => {},
        },
    ],
});
