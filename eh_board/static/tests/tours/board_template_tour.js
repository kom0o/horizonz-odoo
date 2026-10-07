/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour: open the template gallery and confirm the vertical packs
 * render (shown locked here because their base apps are not installed). */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_template_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        { trigger: ".eh_board_header .eh_board_btn:contains(Templates)", run: "click" },
        { trigger: ".eh_board_gallery .eh_board_tpl_card", run: () => {} },
        {
            trigger: ".eh_board_tpl_locked",
            run: () => {},
        },
    ],
});
