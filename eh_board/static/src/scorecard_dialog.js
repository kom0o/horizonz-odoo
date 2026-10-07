/** @odoo-module **/
/* Copyright (C) 2026 ERP Heritage. */
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const copy = (value) => JSON.parse(JSON.stringify(value));

export class ScorecardDialog extends Component {
    static template = "eh_board.ScorecardDialog";
    static components = { Dialog };
    static props = {
        dashboardId: Number,
        options: { type: Object, optional: true },
        onSaved: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.title = _t("KPI scorecard");
        this.nextKey = 1;
        this.state = useState({ loading: true, busy: false, editing: false, dirty: false,
            error: "", data: null, nodes: [], results: [], options: copy(this.props.options || {}) });
        onWillStart(() => this.load());
    }

    errorText(error) { return error?.data?.message || error?.message || _t("The scorecard could not be loaded. Try again."); }
    async load() {
        this.state.busy = true;
        try {
            const data = await this.orm.call("eh.board.dashboard", "get_scorecard", [[this.props.dashboardId], this.state.options]);
            this.install(data);
            this.state.error = "";
        } catch (error) { this.state.error = this.errorText(error); }
        finally { this.state.loading = false; this.state.busy = false; }
    }
    install(data) {
        this.state.data = data;
        this.state.nodes = copy(data.nodes);
        this.state.results = data.results;
        this.state.dirty = false;
    }
    get rows() {
        const rows = [];
        const append = (parent, depth) => {
            if (depth > 5) return;
            for (const node of this.state.nodes.filter((row) => row.parent_key === parent)) {
                rows.push({ node, depth }); append(node.key, depth + 1);
            }
        };
        append("", 0);
        return rows;
    }
    get periods() {
        const periods = new Map();
        for (const node of this.state.nodes) {
            if (node.date_from && node.date_to) {
                const value = `${node.date_from}/${node.date_to}`;
                periods.set(value, { value, label: `${node.date_from} — ${node.date_to}` });
            }
        }
        return [...periods.values()];
    }
    get selectedPeriod() {
        const range = this.state.options.date_range || {};
        return range.start && range.end ? `${range.start}/${range.end}` : "";
    }
    result(key) { return this.state.results.find((row) => row.key === key); }
    ownerName(node) { return this.state.data.owners.find((owner) => owner.id === node.owner_id)?.name || _t("Unavailable owner"); }
    itemName(node) { return this.state.data.items.find((item) => item.id === node.item_id)?.title || _t("Unavailable widget"); }
    number(value) {
        if (value === null || value === undefined || value === "") return "—";
        return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
    }
    actualText(node) {
        const result = this.result(node.key);
        if (result?.actual === null || result?.actual === undefined) return "—";
        return `${this.number(result.actual)} ${result.currency?.code || result.unit || ""}`.trim();
    }
    targetText(node) {
        if (node.kind === "group") return "—";
        return node.direction === "range" ? `${this.number(node.target)} — ${this.number(node.target_upper)}` : this.number(node.target);
    }
    markChanged() { this.state.dirty = true; this.state.results = []; this.state.error = ""; }
    change(node, field, value, numeric = false) {
        node[field] = numeric ? (value === "" ? "" : Number(value)) : value;
        this.markChanged();
    }
    changePeriod(node, field, value) {
        node[field] = value;
        const update = (parent, seen = new Set()) => {
            if (seen.has(parent)) return; seen.add(parent);
            for (const child of this.state.nodes.filter((row) => row.parent_key === parent)) {
                child[field] = value; update(child.key, seen);
            }
        };
        update(node.key); this.markChanged();
    }
    validParents(node) {
        const descendants = new Set([node.key]);
        for (let i = 0; i < 5; i++) {
            for (const other of this.state.nodes) if (descendants.has(other.parent_key)) descendants.add(other.key);
        }
        return this.state.nodes.filter((row) => row.kind === "group" && !descendants.has(row.key));
    }
    changeParent(node, parentKey) {
        node.parent_key = parentKey;
        const parent = this.state.nodes.find((row) => row.key === parentKey);
        if (parent) {
            this.changePeriod(node, "date_from", parent.date_from);
            this.changePeriod(node, "date_to", parent.date_to);
        }
        this.markChanged();
    }
    add(kind, parent = null) {
        const range = this.state.options.date_range || {};
        const node = { key: `new_${Date.now()}_${this.nextKey++}`, parent_key: parent?.key || "", kind,
            name: kind === "group" ? _t("New objective") : _t("New metric"), item_id: false,
            owner_id: parent?.owner_id || this.state.data.default_owner_id,
            date_from: parent?.date_from || range.start || "", date_to: parent?.date_to || range.end || "",
            weight: 1, direction: "higher", note: "" };
        // Empty numeric inputs require a deliberate editor choice, including zero.
        if (kind === "metric") Object.assign(node, { baseline: "", target: "", target_upper: "", baseline_upper: "" });
        else Object.assign(node, { baseline: 0, target: 0, target_upper: 0, baseline_upper: 0 });
        this.state.nodes.push(node); this.markChanged();
    }
    remove(node) {
        const removed = new Set([node.key]);
        for (let i = 0; i < 5; i++) {
            for (const row of this.state.nodes) if (removed.has(row.parent_key)) removed.add(row.key);
        }
        this.state.nodes = this.state.nodes.filter((row) => !removed.has(row.key));
        this.markChanged();
    }
    payload() {
        return copy(this.state.nodes).map((node) => {
            if (node.kind === "metric" && node.direction !== "range") {
                node.target_upper = 0; node.baseline_upper = 0;
            }
            return node;
        });
    }
    async selectPeriod(value) {
        if (!value) delete this.state.options.date_range;
        else {
            const [start, end] = value.split("/");
            this.state.options.date_range = { start, end };
        }
        if (this.state.editing) await this.preview();
        else await this.load();
    }
    edit() { this.state.editing = true; }
    cancelEdit() { this.state.editing = false; this.install(this.state.data); this.state.error = ""; }
    async preview() {
        this.state.busy = true; this.state.error = "";
        try {
            const result = await this.orm.call("eh.board.dashboard", "preview_scorecard", [[this.props.dashboardId], this.payload(), this.state.data.revision, this.state.options]);
            this.state.results = result.results;
            this.state.data.scope = result.scope;
            this.state.dirty = false;
        } catch (error) { this.state.error = this.errorText(error); }
        finally { this.state.busy = false; }
    }
    async save() {
        this.state.busy = true; this.state.error = "";
        try {
            const result = await this.orm.call("eh.board.dashboard", "save_scorecard", [[this.props.dashboardId], this.payload(), this.state.data.revision, this.state.options]);
            this.install(result); this.state.editing = false;
            if (this.props.onSaved) await this.props.onSaved(result);
        } catch (error) { this.state.error = this.errorText(error); }
        finally { this.state.busy = false; }
    }
}
