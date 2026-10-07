/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const READONLY = { create: false, createEdit: false, write: false };
const makeSide = (label) => ({ model_id: false, key: "", aggregate: "count", field: "", label,
    filters: [], date_field: "", date_start: "", date_end: "", fields: [], loading: false });

export class QueryBuilder extends Component {
    static template = "eh_board.QueryBuilder";
    static components = { Dialog, Many2XAutocomplete };
    static props = { dashboardId: Number, onSaved: Function, close: Function };

    setup() {
        this.orm = useService("orm");
        this.nextFilterId = 1;
        this.sides = ["left", "right"];
        this.state = useState({ models: [], companies: [], company_id: false, name: "",
            left: makeSide(_t("Left measure")), right: makeSide(_t("Right measure")),
            join_type: "full", formula: "", formula_label: _t("Calculated"), chart_type: "hbar",
            limit: 30, error: "", busy: false, preview: null, previewKey: "" });
        onWillStart(async () => {
            try {
                const options = await this.orm.call("eh.board.dashboard", "query_options", [[this.props.dashboardId]]);
                Object.assign(this.state, options);
            } catch (error) { this.state.error = this.errorText(error); }
        });
    }

    get title() { return _t("Compare two models"); }
    sideTitle(side) { return side === "left" ? _t("A · Left side") : _t("B · Right side"); }
    modelProps(side) {
        const model = this.state.models.find((record) => record.id === this.state[side].model_id);
        return { activeActions: READONLY, fieldString: this.sideTitle(side), quickCreate: null,
            getDomain: () => [["id", "in", this.state.models.map((record) => record.id)]],
            id: `eh_query_${side}_model`, resModel: "ir.model", searchLimit: 20,
            placeholder: _t("Search readable models…"), value: model ? `${model.name} (${model.model})` : "",
            update: (records) => this.chooseModel(side, records) };
    }
    async chooseModel(side, records) {
        const modelId = records?.[0]?.id || false;
        const label = this.state[side].label;
        Object.assign(this.state[side], makeSide(label), { model_id: modelId, loading: !!modelId });
        if (!modelId) return;
        try {
            const options = await this.orm.call("eh.board.dashboard", "query_options", [[this.props.dashboardId], [modelId]]);
            if (this.state[side].model_id === modelId) this.state[side].fields = options.fields[String(modelId)] || [];
        } catch (error) { this.state.error = this.errorText(error); }
        finally { if (this.state[side].model_id === modelId) this.state[side].loading = false; }
    }
    fields(side, kind) {
        return this.state[side].fields.filter((field) => kind === "key" ? field.key :
            kind === "numeric" ? field.numeric : kind === "date" ? ["date", "datetime"].includes(field.type) : true);
    }
    filterField(side, filter) { return this.state[side].fields.find((field) => field.name === filter.field); }
    filterKind(side, filter) { return this.filterField(side, filter)?.type || "char"; }
    filterChoices(side, filter) { return this.filterField(side, filter)?.selection || []; }
    filterOperators(side, filter) {
        const kind = this.filterKind(side, filter);
        const options = [["=", _t("is equal to")], ["!=", _t("is not equal to")]];
        if (["integer", "float", "monetary", "date", "datetime"].includes(kind)) {
            options.push([">", _t("is greater than")], [">=", _t("is at least")], ["<", _t("is less than")], ["<=", _t("is at most")]);
        }
        if (kind === "char") options.push(["ilike", _t("contains")], ["not ilike", _t("does not contain")]);
        return options;
    }
    addFilter(side) {
        if (this.state[side].filters.length < 12) this.state[side].filters.push({ id: this.nextFilterId++, field: "", operator: "=", value: "", recordLabel: "" });
    }
    removeFilter(side, filter) { this.state[side].filters = this.state[side].filters.filter((item) => item.id !== filter.id); }
    changeFilterField(side, filter, event) {
        filter.field = event.target.value;
        filter.operator = "=";
        filter.value = this.filterKind(side, filter) === "boolean" ? "true" : "";
        filter.recordLabel = "";
    }
    relationProps(side, filter) {
        return { activeActions: READONLY, fieldString: this.filterField(side, filter)?.label || _t("Record"),
            getDomain: () => [], quickCreate: null, resModel: this.filterField(side, filter)?.relation,
            id: `eh_query_filter_${filter.id}`, searchLimit: 20, placeholder: _t("Choose a visible record…"),
            value: filter.recordLabel || "", update: (records) => {
                filter.value = records?.[0]?.id || false;
                filter.recordLabel = records?.[0]?.display_name || records?.[0]?.name || "";
            } };
    }
    changeAggregate(side, event) {
        this.state[side].aggregate = event.target.value;
        if (event.target.value === "count") this.state[side].field = "";
    }
    changeDateField(side, event) {
        this.state[side].date_field = event.target.value;
        if (!event.target.value) this.state[side].date_start = this.state[side].date_end = "";
    }
    filterValue(side, filter) {
        const kind = this.filterKind(side, filter);
        if (kind === "boolean") return filter.value === "true";
        if (kind === "many2one") return filter.value || false;
        if (kind === "datetime" && filter.value) return filter.value.replace("T", " ") + (filter.value.length === 16 ? ":00" : "");
        return filter.value;
    }
    plan() {
        const s = this.state;
        const plan = { version: 1, name: s.name, company_id: Number(s.company_id), join_type: s.join_type,
            formula: s.formula, formula_label: s.formula_label, chart_type: s.chart_type, limit: Number(s.limit) };
        for (const side of this.sides) {
            const v = s[side];
            plan[side] = { model_id: v.model_id, key: v.key, aggregate: v.aggregate,
                field: v.aggregate === "count" ? "" : v.field, label: v.label,
                filters: v.filters.map((filter) => ({ field: filter.field, operator: filter.operator, value: this.filterValue(side, filter) })),
                date_field: v.date_field, date_start: v.date_start, date_end: v.date_end };
        }
        return plan;
    }
    get canPreview() {
        return !!(this.state.name.trim() && this.state.company_id && this.sides.every((side) => {
            const s = this.state[side];
            return s.model_id && s.key && !s.loading && s.label.trim() && (s.aggregate === "count" || s.field)
                && s.filters.every((filter) => filter.field)
                && (!s.date_field || (s.date_start && s.date_end));
        }));
    }
    get previewCurrent() { return !!this.state.preview && this.state.previewKey === JSON.stringify(this.plan()); }
    get canSave() { return this.canPreview && this.previewCurrent && !this.state.busy; }
    errorText(error) { return error?.data?.message || error?.message || _t("The analysis could not be completed."); }
    formatValue(value) { return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 4 }); }
    rowState(row) { return row.matched ? _t("Both sides") : row.left_present ? _t("Left only") : _t("Right only"); }
    async preview() {
        if (!this.canPreview || this.state.busy) return;
        const plan = this.plan(), key = JSON.stringify(plan);
        this.state.busy = true; this.state.error = "";
        try {
            this.state.preview = await this.orm.call("eh.board.dashboard", "preview_query", [[this.props.dashboardId], plan]);
            this.state.previewKey = key;
        } catch (error) { this.state.preview = null; this.state.error = this.errorText(error); }
        finally { this.state.busy = false; }
    }
    async save() {
        if (!this.canSave) return;
        this.state.busy = true; this.state.error = "";
        try {
            const result = await this.orm.call("eh.board.dashboard", "apply_query", [[this.props.dashboardId], this.plan()]);
            await this.props.onSaved(result);
            this.props.close();
        } catch (error) { this.state.error = this.errorText(error); }
        finally { this.state.busy = false; }
    }
}
