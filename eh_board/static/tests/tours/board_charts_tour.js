/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour: the new chart types (polar, heat map, bullet) render. */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_charts_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        { trigger: ".eh_board_widget[data-item-type=polar] .eh_board_polar svg", run: () => {} },
        // clicking a legend item hides/shows that category (interactive legend)
        { trigger: ".eh_board_widget[data-item-type=polar] .eh_board_legend_click .eh_board_legend_item", run: "click" },
        { trigger: ".eh_board_widget[data-item-type=polar] .eh_board_legend_item.o_off", run: () => {} },
        { trigger: ".eh_board_widget[data-item-type=heatmap] .eh_board_heat_table", run: () => {} },
        {
            trigger: ".eh_board_widget[data-item-type=bullet] .eh_board_bullet_track",
            run: () => {},
        },
    ],
});
