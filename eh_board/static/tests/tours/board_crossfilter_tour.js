/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour for cross-filtering: turn on cross-filter mode, click a
 * bar, and a board-wide filter chip appears (every widget re-scopes to it). */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_crossfilter_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        // enter cross-filter mode
        { trigger: ".eh_board_xf", run: "click" },
        { trigger: ".eh_board_xf.o_primary", run: () => {} },
        // click a bar -> pushes a cross-filter chip for that value
        { trigger: ".eh_board_widget[data-item-type=bar] .eh_board_bar", run: "click" },
        {
            trigger: ".eh_board_crossbar .eh_board_chip",
            run: () => {},
        },
    ],
});
