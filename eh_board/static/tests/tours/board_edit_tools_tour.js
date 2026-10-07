/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic tour for the edit-mode tools: duplicate a widget and open the
 * in-canvas Add-filter dialog. */

import { registry } from "@web/core/registry";

function rgb(hex) {
    let value = hex.trim().replace("#", "");
    if (value.length === 3) value = [...value].map((part) => part + part).join("");
    if (!/^[0-9a-f]{6}$/i.test(value)) throw new Error("expected a hex colour, got " + hex);
    return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16) / 255);
}

function luminance(hex) {
    const channels = rgb(hex).map((value) =>
        value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(first, second) {
    const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
    return (light + 0.05) / (dark + 0.05);
}

registry.category("web_tour.tours").add("eh_board_edit_tools_tour", {
    url: "/web#action=eh_board.action_eh_board_open",
    steps: () => [
        { trigger: ".eh_board_app .eh_board_widget", run: () => {} },
        // presentation mode: Play opens a slideshow overlay with controls; step
        // once, then exit back to the board (header restored).
        { trigger: ".eh_board_playbtn", run: "click" },
        { trigger: ".eh_board_present .eh_board_present_ctrl", run: () => {} },
        { trigger: ".eh_board_present_slide .eh_board_widget", run: () => {} },
        { trigger: ".eh_board_present_btn.eh_board_present_play", run: "click" },
        { trigger: ".eh_board_present_ctrl .eh_board_present_exit", run: "click" },
        { trigger: ".eh_board_app:not(.o_kiosk) .eh_board_toolbar", run: () => {} },
        // the top-left main menu drawer
        { trigger: ".eh_board_menubtn", run: "click" },
        { trigger: ".eh_board_menu_drawer .eh_board_menu_item:contains(New dashboard)", run: () => {} },
        { trigger: ".eh_board_menu_drawer .eh_board_menu_item:contains(All Odoo apps)", run: () => {} },
        { trigger: ".eh_board_menubtn", run: "click" },
        { trigger: ".eh_board_header .eh_board_btn:contains(Edit)", run: "click" },
        // the drag grip must be the TOP element at its own centre (not hidden
        // behind the widget header) so it actually receives the drag pointerdown.
        {
            trigger: ".eh_board_grid.o_editing .eh_board_cell .eh_board_move_handle",
            run() {
                const h = document.querySelector(
                    ".eh_board_grid.o_editing .eh_board_cell .eh_board_move_handle");
                const r = h.getBoundingClientRect();
                const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                // The topmost element at the grip's centre must belong to a drag
                // grip (not the widget header) - else the pointerdown is swallowed.
                if (!top || !top.closest(".eh_board_move_handle")) {
                    throw new Error("drag grip is covered by " + (top && top.className));
                }
            },
        },
        // dashboard settings are reachable from the header and render fields
        { trigger: ".eh_board_btn[title='Dashboard settings']", run: "click" },
        { trigger: ".eh_board_settings .eh_board_settings_grid", run: () => {} },
        { trigger: ".eh_board_settings .eh_board_flabel:contains(Colour palette)", run: () => {} },
        {
            trigger: ".eh_board_settings .eh_board_palette_choices",
            run() {
                const choices = document.querySelectorAll(".eh_board_palette_choice");
                if (choices.length !== 5 || [...choices].some((choice) => choice.querySelectorAll("i").length !== 10)) {
                    throw new Error("settings must show five light/dark palette previews");
                }
            },
        },
        { trigger: ".eh_board_settings .eh_board_flabel:contains(Opens with date range)", run: () => {} },
        // the searchable people picker renders (search box + an add option)
        { trigger: ".eh_board_settings .eh_board_userpick input", run: () => {} },
        { trigger: ".eh_board_settings .eh_board_userlist .eh_board_useropt", run: () => {} },
        { trigger: ".modal-footer .btn:contains(Cancel)", run: "click" },
        // Palette selection works in dark mode; old CSS specificity silently
        // forced the default ramp regardless of this select.
        {
            trigger: ".eh_board_palette",
            run() {
                const select = document.querySelector(".eh_board_palette");
                select.value = "ocean";
                select.dispatchEvent(new Event("change", { bubbles: true }));
                const app = document.querySelector(".eh_board_app");
                if (app.dataset.ehTheme !== "dark") {
                    document.querySelector("button[title='Toggle light / dark']").click();
                }
            },
        },
        {
            trigger: ".eh_board_app[data-eh-theme=dark][data-eh-palette=ocean]",
            run() {
                const app = document.querySelector(".eh_board_app");
                const colour = getComputedStyle(app).getPropertyValue("--eh-board-series-1").trim();
                if (colour.toLowerCase() !== "#62b5e5") {
                    throw new Error("dark Ocean palette did not override base theme: " + colour);
                }
            },
        },
        {
            trigger: ".eh_board_app[data-eh-theme=dark][data-eh-palette=ocean]",
            run() {
                const app = document.querySelector(".eh_board_app");
                for (const theme of ["light", "dark"]) {
                    app.dataset.ehTheme = theme;
                    for (const palette of ["default", "ocean", "sunset", "forest", "mono"]) {
                        app.dataset.ehPalette = palette;
                        const style = getComputedStyle(app);
                        const surface = style.getPropertyValue("--eh-board-surface").trim();
                        for (let index = 1; index <= 8; index++) {
                            const colour = style.getPropertyValue(`--eh-board-series-${index}`).trim();
                            const ratio = contrast(colour, surface);
                            if (ratio < 3) {
                                throw new Error(
                                    `${theme}/${palette} series ${index} contrast ${ratio.toFixed(2)}:1`);
                            }
                        }
                    }
                }
                const probe = document.createElement("div");
                app.appendChild(probe);
                for (const accent of ["mint", "blue", "violet", "amber", "rose", "teal", "indigo", "slate"]) {
                    probe.className = `eh_board_accent_${accent}`;
                    const solid = getComputedStyle(probe).getPropertyValue("--accent-solid").trim();
                    const ratio = contrast(solid, "#fff");
                    if (ratio < 4.5) {
                        throw new Error(`${accent} solid KPI contrast ${ratio.toFixed(2)}:1`);
                    }
                }
                probe.remove();
                app.dataset.ehTheme = "dark";
                app.dataset.ehPalette = "ocean";
            },
        },
        // duplicate the KPI widget
        {
            trigger: ".eh_board_widget[data-item-type=kpi] button[title=Duplicate]",
            run: "click",
        },
        { trigger: ".eh_board_widget_title:contains(copy)", run: () => {} },
        // Discard button is present in edit mode (safety net for non-technical users)
        { trigger: ".eh_board_header .eh_board_btn:contains(Discard)", run: () => {} },
        // Delete asks for confirmation instead of deleting on the spot
        { trigger: ".eh_board_widget[data-item-type=kpi] button[title=Remove]", run: "click" },
        { trigger: ".modal-body:contains(cannot be undone)", run: () => {} },
        { trigger: ".modal-footer .btn:contains(Keep it)", run: "click" },
        // still present after cancelling the delete
        { trigger: ".eh_board_widget[data-item-type=kpi]", run: () => {} },
        // export menu offers PDF / Excel / CSV / JSON
        { trigger: ".eh_board_export .eh_board_btn.o_icon", run: "click" },
        { trigger: ".eh_board_export_menu button:contains(PDF)", run: () => {} },
        { trigger: ".eh_board_export_menu button:contains(Excel workbook)", run: () => {} },
        { trigger: ".eh_board_export_menu button:contains(Export for another database)", run: () => {} },
        // ...and every one of them is actually REACHABLE. Existing in the DOM is
        // not enough: the menu used to render in full inside the command bar,
        // which is a scroll container on both axes (overflow-x:auto forces
        // overflow-y:auto), so it was clipped to a 2px sliver and no button could
        // be clicked while every selector above still matched.
        {
            trigger: ".eh_board_export_menu",
            run() {
                const menu = document.querySelector(".eh_board_export_menu");
                // The entry animation slides the menu 4px, so compare where it
                // was PLACED rather than which frame this step caught.
                const raw = menu.getBoundingClientRect();
                const shift = getComputedStyle(menu).transform;
                const offset = shift && shift !== "none"
                    ? new DOMMatrixReadOnly(shift) : { m41: 0, m42: 0 };
                const rect = new DOMRect(raw.x - offset.m41, raw.y - offset.m42,
                                         raw.width, raw.height);
                if (rect.height < 100) {
                    throw new Error("export menu collapsed to " + Math.round(rect.height) + "px");
                }
                if (rect.bottom > window.innerHeight || rect.top < 0
                    || rect.left < 0 || rect.right > window.innerWidth) {
                    throw new Error("export menu falls outside the viewport");
                }
                for (const button of menu.querySelectorAll("button")) {
                    const box = button.getBoundingClientRect();
                    const top = document.elementFromPoint(
                        box.x + box.width / 2, box.y + box.height / 2);
                    if (!top || !top.closest(".eh_board_export_menu")) {
                        throw new Error("export item '" + button.textContent.trim()
                            + "' is covered by " + (top && top.className));
                    }
                }
                // and it hangs off the button that opened it, not off some
                // arbitrary edge: same trailing edge, just below it.
                const toggle = document
                    .querySelector(".eh_board_export .eh_board_btn.o_icon")
                    .getBoundingClientRect();
                if (Math.abs(rect.right - toggle.right) > 2 || rect.top < toggle.bottom) {
                    throw new Error("export menu is not anchored to its button");
                }
            },
        },
        { trigger: ".eh_board_export .eh_board_btn.o_icon", run: "click" },
        // closing it removes the popover from the overlay host. Expressed as a
        // trigger, not an assertion in run(): the re-render is asynchronous, so
        // a synchronous check here races it (it passed on 16 only by luck).
        { trigger: ".eh_board_overlay:empty", run: () => {} },
        // open the in-canvas Add-filter dialog
        { trigger: ".eh_board_header .eh_board_btn:contains(Filter)", run: "click" },
        {
            trigger: ".eh_board_addfilter",
            run() {
                const input = document.querySelector(
                    ".eh_board_addfilter .eh_board_model_picker .o-autocomplete--input");
                if (!input || document.querySelector(".eh_board_addfilter .eh_board_model_picker select")) {
                    throw new Error("filter model picker must be one autocomplete");
                }
                input.value = "res.partner";
                input.dispatchEvent(new Event("input", { bubbles: true }));
            },
        },
        {
            trigger: ".eh_board_addfilter .o-autocomplete--dropdown-item:contains(Contact)",
            run() {
                const menu = document.querySelector(".eh_board_addfilter .o-autocomplete--dropdown-menu");
                if (!menu || /Create(?: and edit)?/i.test(menu.textContent)) {
                    throw new Error("model autocomplete must not offer record creation");
                }
                const option = [...menu.querySelectorAll(".o-autocomplete--dropdown-item")]
                    .find((item) => item.textContent.includes("Contact"));
                if (!option) throw new Error("technical-name search did not find Contact");
                option.click();
            },
        },
        {
            trigger: ".eh_board_addfilter .eh_board_filter_field:has(option[value=name])",
            run() {
                const input = document.querySelector(
                    ".eh_board_addfilter .eh_board_model_picker .o-autocomplete--input");
                if (!input.value.includes("res.partner")) {
                    throw new Error("selected model lost its technical name");
                }
            },
        },
    ],
});
