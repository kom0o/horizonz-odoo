/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * In-canvas "Add filter": pick a model + a field, and a global filter appears
 * on the bar that re-scopes every widget whose model has that field. */

import { _t } from "@web/core/l10n/translation";

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

const READONLY_MODEL_ACTIONS = { create: false, createEdit: false, write: false };

export class AddFilterDialog extends Component {
    static template = "eh_board.AddFilterDialog";
    static components = { Dialog, Many2XAutocomplete };
    static props = { dashboardId: Number, onAdded: Function, close: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            model_id: false, field: "", name: "", models: [], fields: [],
        });
        onWillStart(async () => {
            const meta = await this.orm.call(
                "eh.board.dashboard", "get_builder_meta", [[this.props.dashboardId]]);
            this.state.models = meta.models;
        });
    }

    get selectedModel() {
        return this.state.models.find((model) => model.id === this.state.model_id);
    }

    get modelAutocompleteProps() {
        const model = this.selectedModel;
        return {
            activeActions: READONLY_MODEL_ACTIONS,
            fieldString: _t("Model"),
            getDomain: () => [["id", "in", this.state.models.map((item) => item.id)]],
            id: "eh_board_filter_model",
            placeholder: _t("Search by model name or technical name..."),
            quickCreate: null,
            resModel: "ir.model",
            searchLimit: 20,
            update: this.onModelSelected.bind(this),
            value: model ? `${model.name} (${model.model})` : "",
        };
    }

    async onModelSelected(records) {
        const record = Array.isArray(records) && records.length ? records[0] : null;
        const modelId = record ? parseInt(record.id, 10) || false : false;
        if (modelId === this.state.model_id) return;
        this.state.model_id = modelId;
        this.state.field = "";
        this.state.fields = [];
        if (this.state.model_id) {
            const modelId = this.state.model_id;
            const res = await this.orm.call(
                "eh.board.dashboard", "get_model_fields",
                [[this.props.dashboardId], modelId]);
            // Ignore a slow response for a model the user already replaced.
            if (modelId === this.state.model_id) this.state.fields = res.dimensions;
        }
    }

    get canConfirm() {
        return !!(this.state.model_id && this.state.field);
    }

    async confirm() {
        const res = await this.orm.call("eh.board.dashboard", "add_filter",
            [[this.props.dashboardId], {
                model_id: this.state.model_id,
                field: this.state.field,
                name: this.state.name,
            }]);
        if (res && res.filter) {
            this.props.onAdded(res.filter);
        }
        this.props.close();
    }
}
