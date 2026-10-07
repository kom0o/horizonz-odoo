/** @odoo-module **/
/* Real OWL data selection/preview/apply, injected by the native HttpCase. */
window.ehAuthoringScopeTour = async ({sourceId, modelId}) => {
    const visible = (node) => node && node.getClientRects().length;
    const wait = async (predicate, label) => {
        const end = Date.now() + 25000;
        while (Date.now() < end) {
            const value = predicate();
            if (value) { await new Promise(requestAnimationFrame); if (predicate()) return value; }
            await new Promise((resolve) => setTimeout(resolve, 60));
        }
        throw new Error(`Timed out: ${label}`);
    };
    const button = (root, label) => [...root.querySelectorAll("button")].find(
        (node) => visible(node) && node.textContent.trim() === label);
    const click = async (root, label) => {
        const node = await wait(() => button(root, label), label);
        if (node.disabled) throw new Error(`Disabled: ${label}`);
        node.click();
    };
    await click(document.querySelector(".eh_board_primary_actions"), "Build with AI");
    const dialog = await wait(() => document.querySelector(".eh_board_authoring"), "authoring dialog");
    const modal = dialog.closest(".modal") || dialog.closest(".o_dialog");
    const idle = () => dialog.getAttribute("aria-busy") === "false";
    const select = async (selector, value) => {
        const node = await wait(() => {
            const input = dialog.querySelector(selector);
            return input && !input.disabled && [...input.options].some((option) => option.value === String(value)) ? input : null;
        }, `available choice ${selector}`);
        node.value = String(value);
        node.dispatchEvent(new Event("change", {bubbles: true}));
        await wait(() => idle() && dialog.querySelector(".eh_board_authoring_scope_selected button"), "scope selected");
    };
    await select(".eh_board_authoring_source", sourceId);
    const prompt = dialog.querySelector("textarea");
    prompt.value = "Count the contacts in the selected saved source.";
    prompt.dispatchEvent(new Event("input", {bubbles: true}));
    await wait(() => !button(dialog, "Create proposal")?.disabled, "proposal enabled");
    await click(dialog, "Create proposal");
    await wait(() => idle() && dialog.querySelector(".eh_board_authoring_card .eh_board_kpi_value"), "scoped preview");
    if (dialog.querySelector(".eh_board_kpi_value").textContent.trim() !== "3") {
        throw new Error("Saved-source scope did not produce its three real contacts");
    }
    if (document.querySelectorAll(".eh_board_app .eh_board_widget").length !== 1) {
        throw new Error("Preview persisted a widget");
    }
    const query = dialog.querySelector(".eh_board_authoring_scope_search input");
    query.value = "res.partner";
    query.dispatchEvent(new Event("input", {bubbles: true}));
    await click(dialog, "Search models");
    await wait(() => idle(), "model search finished");
    await select(".eh_board_authoring_model", modelId);
    await wait(() => idle() && dialog.querySelectorAll(".eh_board_authoring_scope_selected button").length === 2 &&
        !dialog.querySelector(".eh_board_authoring_card"), "data change clears prior proposal");
    if (!button(modal, "Add selected widgets")?.disabled) {
        throw new Error("Changed data scope retained an applicable old preview");
    }
    await click(dialog, "Create proposal");
    await wait(() => idle() && dialog.querySelector(".eh_board_authoring_card .eh_board_kpi_value") &&
        !button(modal, "Add selected widgets")?.disabled, "new scoped preview ready");
    await click(modal, "Add selected widgets");
    await wait(() => !document.querySelector(".eh_board_authoring"), "dialog closed after apply");
    await wait(() => document.querySelectorAll(".eh_board_app .eh_board_widget").length === 2 &&
        document.querySelector(".eh_board_app").textContent.includes("Scoped AI contacts"), "selected widget mounted");
    console.log("test successful");
};
