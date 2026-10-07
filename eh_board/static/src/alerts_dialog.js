/** @odoo-module **/
/* In-board threshold alert manager. Rules re-arm after recovery server-side. */

import { uiText } from "./ui_text";

import { _t } from "@web/core/l10n/translation";

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

const NEW_ALERT = () => ({
    id: false, name: "", active: true, item_id: false,
    operator: "gt", threshold: 0, user_id: false,
});

export class AlertsDialog extends Component {
    static template = "eh_board.AlertsDialog";
    uiText = uiText;
    static components = { Dialog };
    static props = { dashboardId: Number, close: Function };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true, saving: false, canEdit: false,
            alerts: [], items: [], users: [], editing: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        const data = await this.orm.call(
            "eh.board.dashboard", "get_alerts", [[this.props.dashboardId]]);
        this.state.alerts = data.alerts || [];
        this.state.items = data.items || [];
        this.state.users = data.users || [];
        this.state.canEdit = !!data.can_edit;
        this.state.loading = false;
    }

    add() {
        if (!this.state.canEdit) return;
        const alert = NEW_ALERT();
        alert.item_id = this.state.items[0] ? this.state.items[0].id : false;
        alert.user_id = this.state.users[0] ? this.state.users[0].id : false;
        this.state.editing = alert;
    }

    edit(alert) {
        if (this.state.canEdit) this.state.editing = { ...alert };
    }

    cancel() { this.state.editing = null; }

    async save() {
        const alert = this.state.editing;
        if (!alert || !alert.item_id || this.state.saving) return;
        this.state.saving = true;
        try {
            await this.orm.call("eh.board.dashboard", "save_alert",
                [[this.props.dashboardId], alert]);
            this.state.editing = null;
            await this.load();
            this.notification.add(_t("Alert saved and armed."), { type: "success" });
        } catch (error) {
            this.notification.add(error.message || String(error), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    async remove(alert) {
        if (!this.state.canEdit) return;
        await this.orm.call("eh.board.dashboard", "delete_alert",
            [[this.props.dashboardId], alert.id]);
        this.state.alerts = this.state.alerts.filter((item) => item.id !== alert.id);
        this.notification.add(_t("Alert deleted."), { type: "info" });
    }

    itemName(id) {
        const item = this.state.items.find((candidate) => candidate.id === id);
        return item ? item.name : _t("Deleted widget");
    }

    userName(id) {
        const user = this.state.users.find((candidate) => candidate.id === id);
        return user ? user.name : _t("User");
    }

    operatorLabel(operator) {
        return { gt: ">", gte: "≥", lt: "<", lte: "≤" }[operator] || operator;
    }
}
