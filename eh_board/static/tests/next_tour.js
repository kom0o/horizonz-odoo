/** @odoo-module **/
/* Native browser checks injected by TestBoardNextUI. They use real RPCs and
 * DOM events; only the server-side metric fixture and outbound providers are
 * controlled by the test. No customer data or external services are needed. */
window.ehBoardNextTour = async function (scenario) {
    const visible = (node) => !!(node && node.getClientRects().length);
    const waitFor = async (predicate, label) => {
        const deadline = Date.now() + 25000;
        while (Date.now() < deadline) {
            const result = predicate();
            if (result) {
                await new Promise((resolve) => requestAnimationFrame(resolve));
                if (predicate()) return result;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        throw new Error(`Timed out waiting for ${label}`);
    };
    const button = (root, text) => [...root.querySelectorAll("button")].find(
        (node) => visible(node) && node.textContent.trim() === text);
    const click = async (root, text) => {
        const node = await waitFor(() => button(root, text), `button ${text}`);
        if (node.disabled) throw new Error(`Button ${text} is unexpectedly disabled`);
        node.click();
    };
    const modalFor = (node) => node.closest(".modal") || node.closest(".o_dialog");
    const app = await waitFor(() => document.querySelector(".eh_board_app .eh_board_widget"), "mounted board");
    if (!app) throw new Error("Board has no widgets");

    if (scenario === "gallery") {
        await click(document.querySelector(".eh_board_header"), "Templates");
        const gallery = await waitFor(() => document.querySelector(".eh_business_gallery"), "business gallery");
        const card = await waitFor(() => [...gallery.querySelectorAll(".eh_business_pack")].find(
            (node) => node.querySelector("h3")?.textContent.trim() === "Browser fixture pack"), "fixture pack");
        await click(card, "Preview my data");
        const preview = await waitFor(() => gallery.querySelector(".eh_business_preview_items"), "real-data preview");
        await waitFor(() => preview.querySelectorAll(".eh_business_preview_item").length === 2,
            "both preview widgets");
        const headline = await waitFor(() => preview.querySelector(".eh_board_kpi_value"), "preview KPI");
        if (headline.textContent.trim() !== "3") throw new Error(`Expected 3 contacts, got ${headline.textContent}`);
        const definition = preview.querySelector(".eh_business_definition");
        if (!definition?.textContent.includes("Count only the three browser fixture contacts")) {
            throw new Error("Metric definition was not exposed in the preview");
        }
        await click(gallery, "Create private draft");
        await waitFor(() => !document.querySelector(".eh_business_gallery"), "closed gallery after creation");
        await waitFor(() => {
            const board = document.querySelector(".eh_board_app");
            const selected = board?.querySelector(".eh_board_switcher option:checked");
            const name = selected?.textContent || board?.querySelector(".eh_board_name")?.textContent;
            return name?.trim() === "Browser fixture pack" && board.querySelectorAll(".eh_board_widget").length === 2;
        }, "created draft mounted with both widgets");
    } else if (scenario === "authoring") {
        await click(document.querySelector(".eh_board_primary_actions"), "Build with AI");
        const authoring = await waitFor(() => document.querySelector(".eh_board_authoring"), "AI authoring dialog");
        const dialog = modalFor(authoring);
        const prompt = await waitFor(() => {
            const input = authoring.querySelector("textarea");
            return input && !input.disabled ? input : null;
        }, "enabled AI prompt");
        const setPrompt = (value) => {
            prompt.value = value;
            prompt.dispatchEvent(new Event("input", { bubbles: true }));
        };
        const idle = () => authoring.getAttribute("aria-busy") === "false";
        const cards = () => [...authoring.querySelectorAll(".eh_board_authoring_card")];
        const boardWidgets = () => document.querySelectorAll(".eh_board_app .eh_board_widget").length;
        setPrompt("Count the browser fixture contacts.");
        await waitFor(() => !button(authoring, "Create proposal")?.disabled, "enabled proposal action");
        await click(authoring, "Create proposal");
        await waitFor(() => idle() && cards().length === 1 && cards()[0].querySelector(".eh_board_kpi_value"),
            "first real-data AI preview");
        if (cards()[0].querySelector(".eh_board_kpi_value").textContent.trim() !== "3") {
            throw new Error("First AI preview did not calculate the three fixture contacts");
        }
        if (!authoring.textContent.includes("Fixture contacts only.") ||
                !authoring.textContent.includes("No sales target was requested or supplied.")) {
            throw new Error("AI assumptions and unavailable data were not displayed");
        }
        if (boardWidgets() !== 1) throw new Error("Preview unexpectedly changed the current dashboard");
        setPrompt("Keep the contact count and add a country breakdown.");
        await waitFor(() => !button(authoring, "Refine proposal")?.disabled, "enabled refinement action");
        await click(authoring, "Refine proposal");
        await waitFor(() => idle() && cards().length === 2 &&
            cards()[1].querySelector(".eh_board_authoring_preview svg"), "refined KPI and real country chart");
        if (boardWidgets() !== 1) throw new Error("Refinement unexpectedly changed the current dashboard");
        const title = cards()[0].querySelector("input.form-control");
        title.value = "Reviewed AI contacts";
        title.dispatchEvent(new Event("change", { bubbles: true }));
        await waitFor(() => authoring.textContent.includes("Options changed. Refresh the preview before applying."),
            "edited proposal requires a new preview");
        if (!button(dialog, "Add selected widgets")?.disabled) {
            throw new Error("A stale preview must not be applied");
        }
        // Refining an edited proposal must not make its older preview trustworthy on undo.
        setPrompt("Keep the edited contact title and the country breakdown.");
        await click(authoring, "Refine proposal");
        await waitFor(() => idle() && !button(dialog, "Add selected widgets")?.disabled &&
            cards()[0].querySelector("input.form-control").value === "Refined AI contacts", "third proposal preview");
        await click(authoring, "Undo proposal change");
        await waitFor(() => cards()[0].querySelector("input.form-control").value === "Reviewed AI contacts",
            "edited proposal restored by undo");
        if (!button(dialog, "Add selected widgets")?.disabled ||
                !authoring.textContent.includes("Options changed. Refresh the preview before applying.")) {
            throw new Error("Undo restored an edited proposal without its required preview refresh");
        }
        await click(authoring, "Refresh preview");
        await waitFor(() => idle() && !authoring.querySelector(".eh_board_authoring_preview_stale") &&
            !button(dialog, "Add selected widgets")?.disabled, "refreshed edited preview");
        // Select only the KPI: the unselected country chart must never be saved.
        cards()[1].querySelector('.eh_board_authoring_select input[type="checkbox"]').click();
        await waitFor(() => !cards()[1].querySelector('.eh_board_authoring_select input[type="checkbox"]').checked,
            "country chart excluded from selection");
        await click(dialog, "Add selected widgets");
        await waitFor(() => !document.querySelector(".eh_board_authoring"), "closed dialog after apply");
        await waitFor(() => boardWidgets() === 2 && document.querySelector(".eh_board_app").textContent.includes("Reviewed AI contacts"),
            "only the reviewed selected KPI added to the dashboard");
    } else if (scenario === "setup") {
        await click(document.querySelector(".eh_board_primary_actions"), "Build with AI");
        const authoring = await waitFor(() => document.querySelector(".eh_board_authoring"), "AI authoring dialog");
        await waitFor(() => authoring.textContent.includes("administrator's provider configuration"), "AI-off diagnostic");
        const prompt = authoring.querySelector("textarea");
        if (!prompt?.disabled || !button(authoring, "Create proposal")?.disabled) {
            throw new Error("AI-off state must disable the prompt and proposal action");
        }
        if (!authoring.textContent.includes("Smart Build remain available without AI")) {
            throw new Error("AI-off state did not explain the available fallback");
        }
        await click(modalFor(authoring), "Cancel");
        await waitFor(() => !document.querySelector(".eh_board_authoring"), "closed AI dialog");
        document.querySelector(".eh_board_menubtn").click();
        const menu = await waitFor(() => document.querySelector(".eh_board_menu_drawer"), "dashboard menu");
        await click(menu, "Connect Sheets or API");
        const remote = await waitFor(() => document.querySelector(".eh-remote-source"), "remote setup dialog");
        const remoteModal = modalFor(remote);
        if (!remote.textContent.includes("Odoo model record rules do not filter these rows")) {
            throw new Error("Remote source audience scope is missing");
        }
        if (!button(remoteModal, "Save and refresh")?.disabled) {
            throw new Error("Empty remote configuration should not be saved");
        }
        const provider = remote.querySelector("select");
        provider.value = "sheets";
        provider.dispatchEvent(new Event("change", { bubbles: true }));
        await waitFor(() => remote.querySelector('input[type="file"]'), "private Sheets service-account setup");
        if (remote.querySelectorAll("select")[1].value !== "service_account") {
            throw new Error("Authentication selector disagrees with the service-account setup form");
        }
        if (!remote.textContent.includes("Share this spreadsheet") || !remote.textContent.includes("read-only Sheets access")) {
            throw new Error("Private Sheets setup instructions are missing");
        }
        if (!button(remoteModal, "Save and refresh")?.disabled) {
            throw new Error("Sheets setup without credentials should not be saved");
        }
        await click(remoteModal, "Close");
        await waitFor(() => !document.querySelector(".eh-remote-source"), "closed remote setup");
    } else {
        throw new Error(`Unknown smoke scenario: ${scenario}`);
    }
    console.log("test successful");
};
