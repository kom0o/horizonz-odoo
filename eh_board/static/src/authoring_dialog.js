/** @odoo-module **/
/* Copyright (C) 2026 ERP Heritage. */
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { BoardItem } from "./board_item";
import "./registry";

const copy = (value) => JSON.parse(JSON.stringify(value));

export class AuthoringDialog extends Component {
    static template = "eh_board.AuthoringDialog";
    static components = { Dialog, BoardItem };
    static props = {
        dashboardId: Number,
        options: { type: Object, optional: true },
        onSaved: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.history = [];
        this.state = useState({
            loading: true, busy: false, prompt: "", error: "", options: {},
            plan: null, previews: [], selected: [], replacementIds: [],
            replace: false, stale: false, historyCount: 0,
            dataScope: {models: [], sources: []}, modelQuery: "", scopeLabels: {},
        });
        this.title = _t("Create with AI");
        this.chartLabels = {
            tile: _t("Metric"), kpi: _t("KPI"), bar: _t("Bar"), hbar: _t("Horizontal bar"),
            column: _t("Stacked column"), line: _t("Line"), area: _t("Area"),
            pie: _t("Pie"), doughnut: _t("Doughnut"),
        };
        this.periodLabels = {
            none: _t("Metric default / all time"), today: _t("Today"), yesterday: _t("Yesterday"),
            this_week: _t("This week"), last_week: _t("Last week"),
            this_month: _t("This month"), last_month: _t("Last month"),
            this_quarter: _t("This quarter"), last_quarter: _t("Last quarter"),
            this_year: _t("This year"), last_year: _t("Last year"),
            wtd: _t("Week to date"), mtd: _t("Month to date"), qtd: _t("Quarter to date"), ytd: _t("Year to date"),
            last_7: _t("Last 7 days"), last_30: _t("Last 30 days"),
            last_90: _t("Last 90 days"), last_365: _t("Last 365 days"),
        };
        onWillStart(async () => {
            try {
                this.state.options = this.props.options || await this.orm.call(
                    "eh.board.dashboard", "get_authoring_options", [[this.props.dashboardId]]);
                this.state.dataScope = copy(this.state.options.data_scope || {models: [], sources: []});
            } catch (error) {
                this.state.error = this.errorMessage(error);
            } finally {
                this.state.loading = false;
            }
        });
    }

    errorMessage(error) {
        return error?.data?.message || error?.message || _t("This request could not be completed. Your dashboard is unchanged.");
    }

    get metrics() { return this.state.options.metrics || []; }
    get scopeCount() { return this.state.dataScope.models.length + this.state.dataScope.sources.length; }
    get scopeSelections() {
        return ["models", "sources"].flatMap((kind) => this.state.dataScope[kind].map((id) => ({
            kind, id, key: `${kind}:${id}`, label: this.state.scopeLabels[`${kind}:${id}`] || String(id),
        })));
    }
    async searchModels() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            this.state.options.model_choices = await this.orm.call(
                "eh.board.dashboard", "search_authoring_models", [[this.props.dashboardId], this.state.modelQuery]);
        } catch (error) { this.state.error = this.errorMessage(error); }
        finally { this.state.busy = false; }
    }
    async addScope(kind, event) {
        const id = Number(event.target.value);
        event.target.value = "";
        if (!id || this.scopeCount >= 3 || this.state.dataScope[kind].includes(id)) return;
        const choices = kind === "models" ? this.state.options.model_choices : this.state.options.source_choices;
        const choice = (choices || []).find((row) => row.id === id);
        if (!choice) return;
        this.state.scopeLabels[`${kind}:${id}`] = choice.name;
        await this.changeScope(kind, id, true);
    }
    async changeScope(kind, id, add = false) {
        if (this.state.busy) return;
        const scope = copy(this.state.dataScope);
        scope[kind] = add ? [...scope[kind], id] : scope[kind].filter((value) => value !== id);
        this.state.busy = true;
        this.state.error = "";
        try {
            const options = await this.orm.call("eh.board.dashboard", "get_authoring_options", [
                [this.props.dashboardId], scope,
            ]);
            this.state.dataScope = options.data_scope;
            this.state.options = options;
            this.state.plan = null;
            this.state.previews = [];
            this.state.selected = [];
            this.state.stale = false;
            this.history = [];
            this.state.historyCount = 0;
        } catch (error) { this.state.error = this.errorMessage(error); }
        finally { this.state.busy = false; }
    }
    get canGenerate() {
        return this.state.options.available && this.metrics.length && this.state.prompt.trim()
            && this.state.prompt.length <= 2000 && !this.state.busy;
    }
    get canApply() {
        if (this.state.busy || this.state.stale || !this.state.selected.length) return false;
        if (this.state.replace && !this.state.replacementIds.length) return false;
        return this.state.selected.every((id) => this.state.previews.some((row) => row.id === id && !row.error));
    }
    get limitsText() {
        const limits = this.state.options.limits;
        return limits ? _t("%s AI requests remaining today (UTC).").replace("%s", limits.remaining) : "";
    }
    get applyLabel() {
        return this.state.replace ? _t("Replace selected draft widgets") : _t("Add selected widgets");
    }
    metric(row) { return this.metrics.find((metric) => metric.id === row.metric_id) || {}; }
    row(id) { return (this.state.plan?.items || []).find((row) => row.id === id); }
    metricPrompt(metric) {
        this.state.prompt = _t("Create a dashboard for %s.").replace("%s", metric.title);
    }
    remember() {
        if (!this.state.plan) return;
        this.history.push(copy({plan: this.state.plan, previews: this.state.previews, selected: this.state.selected, stale: this.state.stale}));
        if (this.history.length > 5) this.history.shift();
        this.state.historyCount = this.history.length;
    }
    undo() {
        if (this.state.busy || !this.history.length) return;
        const previous = this.history.pop();
        this.state.plan = previous.plan;
        this.state.previews = previous.previews;
        this.state.selected = previous.selected;
        this.state.stale = Boolean(previous.stale);
        this.state.error = "";
        this.state.historyCount = this.history.length;
    }
    setResult(result, remember = true) {
        if (!result?.ok) {
            this.state.error = result?.error || _t("No usable proposal was returned.");
            if (result?.limits) this.state.options.limits = result.limits;
            return;
        }
        if (remember) this.remember();
        this.state.plan = result.plan;
        this.state.previews = result.previews || [];
        this.state.selected = this.state.previews.filter((row) => !row.error).map((row) => row.id);
        this.state.stale = false;
        this.state.error = "";
        if (result.limits) this.state.options.limits = result.limits;
    }
    async generate() {
        if (!this.canGenerate) return;
        this.state.busy = true;
        this.state.error = "";
        try {
            const result = await this.orm.call("eh.board.dashboard", "generate_authoring_plan", [
                [this.props.dashboardId], this.state.prompt.trim(), this.state.plan ? copy(this.state.plan) : null,
                copy(this.state.dataScope),
            ]);
            this.setResult(result);
        } catch (error) {
            this.state.error = this.errorMessage(error);
        } finally {
            this.state.busy = false;
        }
    }
    toggleSelected(id) {
        this.state.selected = this.state.selected.includes(id)
            ? this.state.selected.filter((key) => key !== id) : [...this.state.selected, id];
    }
    toggleReplacement(id) {
        this.state.replacementIds = this.state.replacementIds.includes(id)
            ? this.state.replacementIds.filter((key) => key !== id) : [...this.state.replacementIds, id];
    }
    changeRow(id, key, value) {
        if (this.state.busy) return;
        if (!this.state.stale) this.remember();
        const row = this.row(id);
        row[key] = value;
        if (key === "item_type") {
            if (["tile", "kpi"].includes(value)) row.dimension = "";
            else if (!row.dimension) row.dimension = (this.metric(row).allowed_dimensions || [])[0]?.field || "";
        }
        this.state.stale = true;
    }
    async refreshPreview() {
        if (this.state.busy || !this.state.plan) return;
        this.state.busy = true;
        this.state.error = "";
        try {
            const selected = [...this.state.selected];
            const result = await this.orm.call("eh.board.dashboard", "preview_authoring_plan", [
                [this.props.dashboardId], copy(this.state.plan), copy(this.state.dataScope),
            ]);
            this.setResult(result, false);
            if (result?.ok) this.state.selected = selected.filter((id) => this.state.previews.some((row) => row.id === id && !row.error));
        } catch (error) {
            this.state.error = this.errorMessage(error);
        } finally {
            this.state.busy = false;
        }
    }
    async apply() {
        if (!this.canApply) return;
        this.state.busy = true;
        this.state.error = "";
        try {
            const result = await this.orm.call("eh.board.dashboard", "apply_authoring_plan", [
                [this.props.dashboardId], copy(this.state.plan), [...this.state.selected],
                this.state.replace ? [...this.state.replacementIds] : [],
                copy(this.state.dataScope),
            ]);
            this.props.close();
            await this.props.onSaved(result);
        } catch (error) {
            this.state.error = this.errorMessage(error);
        } finally {
            this.state.busy = false;
        }
    }
}
