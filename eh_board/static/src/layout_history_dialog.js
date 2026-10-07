/** @odoo-module **/

import { uiText } from "./ui_text";

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class LayoutHistoryDialog extends Component {
    static template = "eh_board.LayoutHistoryDialog";
    uiText = uiText;
    static components = { Dialog };
    static props = {
        dashboardId: Number,
        canEdit: Boolean,
        onRestored: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ loading: true, restoring: false, versions: [] });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.versions = await this.orm.call(
            "eh.board.dashboard", "get_layout_history", [[this.props.dashboardId]]);
        this.state.loading = false;
    }

    async restore(version) {
        if (!this.props.canEdit || version.active || this.state.restoring) return;
        this.state.restoring = true;
        try {
            const result = await this.orm.call(
                "eh.board.dashboard", "restore_layout",
                [[this.props.dashboardId], version.id]);
            this.props.onRestored(result);
            this.props.close();
        } catch (error) {
            this.notification.add(error.message || String(error), { type: "danger" });
        }
        this.state.restoring = false;
    }
}
