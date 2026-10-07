/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Smart insights: a plain-language read of the board's numbers. Computed on
 * the server offline (no key required); a BYO-key LLM can enrich the same text
 * later. Always available, never a blank "AI unavailable" wall. */

import { uiText } from "./ui_text";

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class InsightsDialog extends Component {
    static template = "eh_board.InsightsDialog";
    uiText = uiText;
    static components = { Dialog };
    static props = { dashboardId: Number, options: { type: Object, optional: true }, close: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            insights: [], loading: true,
            aiAvailable: false, aiBusy: false, narrative: "", provider: "",
        });
        onWillStart(async () => {
            const [insights, aiAvailable] = await Promise.all([
                this.orm.call("eh.board.dashboard", "get_insights", [[this.props.dashboardId], this.props.options || {}]),
                this.orm.call("eh.board.dashboard", "ai_available", []),
            ]);
            this.state.insights = insights;
            this.state.aiAvailable = !!aiAvailable;
            this.state.loading = false;
        });
    }

    /** Ask the customer's own LLM to rewrite the verified insights into a short
     *  narrative. Silently keeps the offline list if anything fails. */
    async explainWithAi() {
        if (this.state.aiBusy) return;
        this.state.aiBusy = true;
        try {
            const res = await this.orm.call(
                "eh.board.dashboard", "get_ai_insights", [[this.props.dashboardId], this.props.options || {}]);
            if (res && res.source === "llm" && res.narrative) {
                this.state.narrative = res.narrative;
                this.state.provider = res.provider || "";
            }
        } catch {
            // fall through - the offline insights remain on screen
        }
        this.state.aiBusy = false;
    }
}
