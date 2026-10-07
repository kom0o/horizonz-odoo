/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour for the runtime global filter bar and click-to-drill:
 * assert the global field filter renders, then click a bar and land on the
 * filtered records list. */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_filter_drill_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        // the global field filter (Country) is on the bar
        {
            trigger: ".eh_board_filters .eh_board_filterbar .fa-filter",
            run: () => {},
        },
        // click a bar -> drill into the underlying records
        { trigger: ".eh_board_widget[data-item-type=bar] .eh_board_bar", run: "click" },
        {
            trigger: ".o_list_view, .o_list_renderer",
            run: () => {},
        },
    ],
});
