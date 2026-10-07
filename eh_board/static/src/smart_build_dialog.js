/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Deterministic whole-dashboard generation from one readable Odoo model. */

import { uiText } from "./ui_text";

import { _t } from "@web/core/l10n/translation";

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

const READ_ONLY = { create: false, createEdit: false, write: false };

export class SmartBuildDialog extends Component {
    static template = "eh_board.SmartBuildDialog";
    uiText = uiText;
    static components = { Dialog, Many2XAutocomplete };
    static props = {
        dashboardId: Number,
        hasItems: { type: Boolean, optional: true },
        onBuilt: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            busy: false,
            modelId: false,
            models: [],
            replace: false,
        });
        onWillStart(async () => {
            const meta = await this.orm.call(
                "eh.board.dashboard", "get_builder_meta", [[this.props.dashboardId]]);
            this.state.models = meta.models || [];
            this.state.loading = false;
        });
    }

    get selectedModel() {
        return this.state.models.find((model) => model.id === this.state.modelId);
    }

    get modelAutocompleteProps() {
        const selected = this.selectedModel;
        return {
            activeActions: READ_ONLY,
            fieldString: _t("Business model"),
            getDomain: () => [["id", "in", this.state.models.map((model) => model.id)]],
            id: "eh_board_smart_build_model",
            placeholder: _t("Search Sale Analysis, Invoice Analysis, sale.report..."),
            quickCreate: null,
            resModel: "ir.model",
            searchLimit: 30,
            update: this.onModelSelected.bind(this),
            value: selected ? `${selected.name} (${selected.model})` : "",
        };
    }

    onModelSelected(records) {
        const record = Array.isArray(records) && records.length ? records[0] : null;
        this.state.modelId = record ? parseInt(record.id, 10) || false : false;
    }

    async build() {
        if (!this.state.modelId || this.state.busy) return;
        this.state.busy = true;
        try {
            const result = await this.orm.call(
                "eh.board.dashboard", "smart_build",
                [[this.props.dashboardId], this.state.modelId, this.state.replace]);
            this.props.close();
            this.props.onBuilt(result || {});
        } catch (error) {
            this.notification.add(
                (error && error.message) || _t("Dashboard generation failed."),
                { type: "danger" });
            this.state.busy = false;
        }
    }
}
