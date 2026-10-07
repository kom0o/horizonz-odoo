/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour: the pivot / cross-tab matrix widget renders as a real
 * HTML table with row headers, a heat-mapped body and a grand-total cell. */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_board_pivot_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        // the pivot widget mounted a real table
        { trigger: ".eh_board_widget[data-item-type=pivot] .eh_board_pivot_table", run: () => {} },
        // it has a pinned row header
        { trigger: ".eh_board_pivot_table .eh_board_pivot_rowhead", run: () => {} },
        // and a grand-total cell in the footer
        {
            trigger: ".eh_board_pivot_table .eh_board_pivot_foot .eh_board_pivot_grand",
            run: () => {},
        },
        // Average measure keeps its value and adds a percentage companion.
        {
            trigger: ".eh_board_widget[data-item-type=pivot] .eh_board_percent_col",
            run() {
                const table = document.querySelector(
                    ".eh_board_widget[data-item-type=pivot] .eh_board_pivot_table");
                if (!table || !table.textContent.includes("%")) {
                    throw new Error("Pivot percentage companion column did not render");
                }
                // The seeded measure is an AVERAGE, so its rows do not add up
                // to the row total: the header must say the number is a
                // percentage OF that average, not a share of it.
                if (!table.textContent.includes("% of row avg")) {
                    throw new Error(
                        "percentage column on an average measure must not be "
                        + "labelled as a share of the row total");
                }
            },
        },
        // Individual-record list renders selected model fields as real columns.
        {
            trigger: ".eh_board_widget[data-item-type=list] .eh_board_list table",
            run() {
                const table = document.querySelector(
                    ".eh_board_widget[data-item-type=list] .eh_board_list table");
                const text = table ? table.textContent : "";
                if (!text.includes("Name") || !text.includes("Country")) {
                    throw new Error("Selected record-list fields did not render");
                }
            },
        },
        { trigger: ".eh_board_header .eh_board_btn:contains(Edit)", run: "click" },
        {
            trigger: ".eh_board_widget[data-item-type=list] button[title=Configure]",
            run: "click",
        },
        { trigger: ".eh_board_editor #eh_board_list_mode", run: () => {} },
        {
            trigger: ".eh_board_editor .eh_board_record_fields .eh_board_fieldpick",
            run() {
                const mode = document.querySelector("#eh_board_list_mode");
                const chips = document.querySelectorAll(".eh_board_selected_fields .eh_board_field_chip");
                if (!mode || mode.value !== "records" || chips.length !== 2) {
                    throw new Error("Record-list field chooser did not round-trip selected columns");
                }
            },
        },
    ],
});
