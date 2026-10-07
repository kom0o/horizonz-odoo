/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * The widget builder: a tabbed (Data / Display / Actions), multi-measure
 * configurator with a live preview. Everything is validated server-side and
 * previewed without persisting until saved. */

import { uiText } from "./ui_text";

import { Component, useState, onWillStart } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { DomainSelector } from "@web/core/domain_selector/domain_selector";
import { useService } from "@web/core/utils/hooks";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { BoardItem } from "./board_item";
import { RichEditor } from "./rich_editor";
import { SourceStudio } from "./source_studio";
import { RemoteSourceDialog } from "./remote_source_dialog";
import "./registry";

const getTypes = () => [
    { key: "tile", label: _t("Tile"), group: "kpi", icon: "fa-hashtag" },
    { key: "kpi", label: _t("KPI"), group: "kpi", icon: "fa-bullseye" },
    { key: "gauge", label: _t("Gauge"), group: "kpi", icon: "fa-tachometer" },
    { key: "bar", label: _t("Bar"), group: "chart", icon: "fa-bar-chart" },
    { key: "column", label: _t("Stacked"), group: "chart", icon: "fa-bars" },
    { key: "hbar", label: _t("Horizontal"), group: "chart", icon: "fa-align-left" },
    { key: "line", label: _t("Line"), group: "chart", icon: "fa-line-chart" },
    { key: "area", label: _t("Area"), group: "chart", icon: "fa-area-chart" },
    { key: "pie", label: _t("Pie"), group: "chart", icon: "fa-pie-chart" },
    { key: "doughnut", label: _t("Doughnut"), group: "chart", icon: "fa-circle-o" },
    { key: "radar", label: _t("Radar"), group: "chart", icon: "fa-star-o" },
    { key: "polar", label: _t("Polar"), group: "chart", icon: "fa-life-ring" },
    { key: "radial", label: _t("Radial"), group: "chart", icon: "fa-circle-o-notch" },
    { key: "rose", label: _t("Rose"), group: "chart", icon: "fa-pagelines" },
    { key: "funnel", label: _t("Funnel"), group: "chart", icon: "fa-filter" },
    { key: "pyramid", label: _t("Pyramid"), group: "chart", icon: "fa-sort-amount-asc" },
    { key: "scatter", label: _t("Scatter"), group: "chart", icon: "fa-braille" },
    { key: "map", label: _t("Map"), group: "chart", icon: "fa-globe" },
    { key: "bullet", label: _t("Bullet"), group: "kpi", icon: "fa-tachometer" },
    { key: "heatmap", label: _t("Heat Map"), group: "table", icon: "fa-th" },
    { key: "list", label: _t("List"), group: "table", icon: "fa-table" },
    { key: "pivot", label: _t("Pivot"), group: "table", icon: "fa-th" },
    { key: "decomp", label: _t("Decomposition"), group: "table", icon: "fa-sitemap" },
    { key: "slicer", label: _t("Slicer"), group: "control", icon: "fa-filter" },
    { key: "richtext", label: _t("Text"), group: "content", icon: "fa-font" },
    { key: "todo", label: _t("To-Do"), group: "content", icon: "fa-check-square-o" },
];

const getVerbs = () => [
    { key: "count", label: _t("Count") },
    { key: "count_distinct", label: _t("Distinct count") },
    { key: "sum", label: _t("Sum") },
    { key: "avg", label: _t("Average") },
    { key: "max", label: _t("Maximum") },
    { key: "min", label: _t("Minimum") },
    { key: "formula", label: _t("Calculated") },
];

const ACCENTS = ["mint", "blue", "violet", "amber", "rose", "teal", "indigo", "slate"];
const CUSTOM_COLORS = [
    "#2563a9", "#087f5b", "#986400", "#2e7d32",
    "#6842a8", "#c23b4a", "#a33f73", "#b84a1b",
];
const READONLY_MODEL_ACTIONS = { create: false, createEdit: false, write: false };

export class AddItemDialog extends Component {
    static template = "eh_board.AddItemDialog";
    uiText = uiText;
    static components = { BoardItem, DomainSelector, Many2XAutocomplete, RichEditor };
    static props = {
        dashboardId: Number,
        itemId: { type: [Number, { value: null }], optional: true },
        onSaved: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.types = getTypes();
        this.verbs = getVerbs();
        this.accents = ACCENTS;
        this.state = useState({
            tab: "data",
            title: "",
            item_type: "bar",
            model_id: false,
            model_name: "",
            source_id: false,
            provider: "orm",
            domain: "[]",
            measureList: [{ verb: "count", label: "", field: "", format: "compact", unit: "", formula: "", calculation: "none", multiplier: 1, currency_id: false }],
            dimension: "",
            secondary_dimension: "",
            list_mode: "records",
            listFields: [],
            granularity: "month",
            date_field: "",
            default_date_filter: "none",
            sort_mode: "value_desc",
            sort_field: "",
            sort_order: "desc",
            include_archived: false,
            record_limit_visibility: false,
            record_limit: 0,
            number_format: "compact",
            data_label_type: "value",
            target: 0,
            targetSchedule: [],
            compare: "none",
            content: _t("<h2>Heading</h2><p>Your text here.</p>"),
            description: "",
            domainOpen: false,
            matchCount: null,
            fieldSearch: "",
            fieldsOpen: false,
            // display
            accent: "mint",
            tile_style: "soft",
            show_legend: true,
            show_values: true,
            show_grid: true,
            semi_circle: false,
            stacked: false,
            smooth: false,
            goal_value: 0,
            combo_line: false,
            color_mode: "theme",
            chartOptions: {},
            slicer_display: "auto",
            customColors: [...CUSTOM_COLORS],
            show_trend: true,
            // advanced
            cumulative: false,
            fill_gaps: true,
            group_others: false,
            // conditional formatting
            condRules: [],
            // actions
            click_action: "records",
            target_dashboard_id: false,
            window_action_id: false,
            window_action_name: "",
            drill_field: "",
            drillFields: [],
            // meta
            models: [],
            sources: [],
            canSql: false,
            currencies: [],
            boards: [],
            dimFields: [],
            measureFields: [],
            recordFields: [],
            preview: { meta: null, payload: { error: _t("Configure a widget to preview it.") } },
            previewing: false,
        });
        this._debounce = null;
        this.BoardItem = BoardItem;
        onWillStart(async () => {
            const meta = await this.orm.call(
                "eh.board.dashboard", "get_builder_meta", [[this.props.dashboardId]]);
            this.state.models = meta.models;
            this.state.sources = meta.sources || [];
            this.state.canSql = !!meta.can_sql;
            this.state.currencies = meta.currencies || [];
            this.state.boards = meta.boards || [];
            if (this.props.itemId) {
                await this._loadConfig();
            }
            this.refreshPreview();
            this._refreshCount();
        });
    }

    async _loadConfig() {
        const cfg = await this.orm.call(
            "eh.board.dashboard", "get_item_config",
            [[this.props.dashboardId], this.props.itemId]);
        Object.assign(this.state, {
            item_type: cfg.item_type, title: cfg.title, model_id: cfg.model_id,
            source_id: cfg.provider && cfg.provider !== "orm" ? cfg.source_id : false,
            provider: cfg.provider || "orm",
            model_name: cfg.model_name || "", domain: cfg.domain || "[]",
            measureList: (cfg.measures && cfg.measures.length)
                ? cfg.measures.map((m) => ({
                    verb: m.verb, label: m.label || "", field: m.field || "",
                    format: m.number_format || "compact", unit: m.unit || "",
                    as_line: !!m.as_line,
                    formula: m.formula || "",
                    calculation: m.table_calculation || "none",
                    multiplier: m.multiplier || 1,
                    currency_id: m.currency_id || false }))
                : [{ verb: "count", label: "", field: "", format: "compact", unit: "", formula: "", calculation: "none", multiplier: 1, currency_id: false }],
            target: cfg.target || 0,
            targetSchedule: Array.isArray(cfg.target_schedule)
                ? cfg.target_schedule.map((point) => ({ ...point })) : [],
            compare: cfg.compare || "none",
            dimension: cfg.dimension, secondary_dimension: cfg.secondary_dimension || "",
            list_mode: cfg.list_mode || "grouped",
            listFields: Array.isArray(cfg.list_fields) ? cfg.list_fields : [],
            granularity: cfg.granularity || "month", date_field: cfg.date_field || "",
            default_date_filter: cfg.default_date_filter || "none",
            accent: cfg.accent || "mint", tile_style: cfg.tile_style || "soft",
            content: cfg.content || "", sort_mode: cfg.sort_mode || "value_desc",
            sort_field: cfg.sort_field || "", sort_order: cfg.sort_order || "desc",
            include_archived: cfg.include_archived || false,
            record_limit_visibility: cfg.record_limit_visibility || false,
            record_limit: cfg.record_limit || 0, number_format: cfg.number_format || "compact",
            data_label_type: cfg.data_label_type || "value",
            show_legend: cfg.show_legend, show_values: cfg.show_values, show_grid: cfg.show_grid,
            semi_circle: cfg.semi_circle, stacked: cfg.stacked, smooth: cfg.smooth,
            goal_value: cfg.goal_value || 0, combo_line: cfg.combo_line,
            cumulative: cfg.cumulative, fill_gaps: cfg.fill_gaps, group_others: cfg.group_others,
            click_action: cfg.click_action || "records", drill_field: cfg.drill_field || "",
            target_dashboard_id: cfg.target_dashboard_id || false,
            window_action_id: cfg.window_action_id || false,
            window_action_name: cfg.window_action_name || "",
            drillFields: Array.isArray(cfg.drill_fields) ? cfg.drill_fields : [],
            description: cfg.description || "",
            condRules: Array.isArray(cfg.conditional_rules) ? cfg.conditional_rules : [],
            color_mode: cfg.color_mode || "theme",
            chartOptions: cfg.chart_options || {},
            slicer_display: (cfg.chart_options || {}).slicer_display || "auto",
            customColors: Array.isArray((cfg.chart_options || {}).series_colors)
                ? CUSTOM_COLORS.map((fallback, index) =>
                    /^#[0-9a-f]{6}$/i.test((cfg.chart_options.series_colors[index] || ""))
                        ? cfg.chart_options.series_colors[index] : fallback)
                : [...CUSTOM_COLORS],
            show_trend: cfg.show_trend !== false,
        });
        if (cfg.model_id) {
            await this._loadFields(cfg.model_id);
        } else if (this.state.source_id) {
            this._loadSourceFields(this.selectedSource);
        }
    }

    async _loadFields(modelId) {
        const fields = await this.orm.call(
            "eh.board.dashboard", "get_model_fields",
            [[this.props.dashboardId], modelId]);
        // Ignore a slow response for a model the user already replaced.
        if (modelId !== this.state.model_id) return;
        this.state.dimFields = fields.dimensions;
        this.state.measureFields = fields.measures;
        this.state.recordFields = fields.columns || [];
    }

    // -- derived ------------------------------------------------------------
    get isEdit() { return !!this.props.itemId; }
    get dialogTitle() { return this.isEdit ? _t("Edit widget") : _t("Create a widget"); }
    get needsData() { return !["richtext", "todo"].includes(this.state.item_type); }
    get selectedSource() {
        return this.state.sources.find((source) => source.id === this.state.source_id);
    }
    get advancedSources() {
        return this.state.sources.filter((source) => source.provider !== "orm");
    }
    get isAdvancedSource() { return !!this.state.source_id; }
    get isTabularSource() {
        const source = this.selectedSource;
        return !!(source && (source.tabular || ["file", "rest", "sheets"].includes(source.provider)));
    }
    // Existing templates use this name for column wells; keep them compatible.
    get isFileSource() { return this.isTabularSource; }
    get isFixedSource() {
        return this.selectedSource && ["join", "sql"].includes(this.selectedSource.provider);
    }
    get isSlicer() { return this.state.item_type === "slicer"; }
    // A slicer needs a model + a field but no measure; a chart/table needs both.
    get isList() { return this.state.item_type === "list"; }
    get isPivot() { return this.state.item_type === "pivot"; }
    get isRecordList() { return this.isList && this.state.list_mode === "records"; }
    get isTableType() { return this.isList || this.isPivot; }
    get needsMeasure() { return this.needsData && !this.isSlicer && !this.isRecordList && !this.isFixedSource; }
    get needsDimension() {
        return !this.isRecordList && !this.isFixedSource
            && !["kpi", "tile", "gauge", "bullet", "richtext", "todo"].includes(this.state.item_type);
    }
    get isChartType() {
        return !["kpi", "tile", "gauge", "bullet", "slicer", "decomp", "richtext", "todo"].includes(this.state.item_type);
    }
    get isTile() { return ["tile", "kpi"].includes(this.state.item_type); }
    get isPie() { return ["pie", "doughnut"].includes(this.state.item_type); }
    get isBarType() { return ["bar", "column", "hbar"].includes(this.state.item_type); }
    get isLineType() { return ["line", "area"].includes(this.state.item_type); }
    get isRadial() { return ["radar", "polar", "radial", "rose"].includes(this.state.item_type); }
    get isFunnelType() { return ["funnel", "pyramid"].includes(this.state.item_type); }
    get isScatter() { return this.state.item_type === "scatter"; }
    get showConditional() {
        return this.isTile || ["list", "pivot"].includes(this.state.item_type);
    }
    // Every widget can carry an action + a description; only true content blocks
    // (rich text) skip the data-driven tabs.
    get hasActions() { return this.needsData; }
    get hasAdvanced() { return this.isChartType || this.isTile; }
    get dateFields() {
        return this.state.dimFields.filter((d) => d.ttype === "date" || d.ttype === "datetime");
    }
    get selectedModel() {
        return this.state.models.find((model) => model.id === this.state.model_id);
    }
    get colorSlots() {
        const count = this.state.color_mode === "measure"
            ? Math.max(1, Math.min(this.state.measureList.length, 8)) : 8;
        return this.state.customColors.slice(0, count);
    }
    measureFieldChoices(measure) {
        return measure.verb === "count_distinct"
            ? this.state.recordFields : this.state.measureFields;
    }
    get modelAutocompleteProps() {
        const model = this.selectedModel;
        return {
            activeActions: READONLY_MODEL_ACTIONS,
            fieldString: _t("Model"),
            getDomain: () => [["id", "in", this.state.models.map((item) => item.id)]],
            id: "eh_board_widget_model",
            placeholder: _t("Search by model name or technical name..."),
            quickCreate: null,
            resModel: "ir.model",
            searchLimit: 20,
            update: this.onModelSelected.bind(this),
            value: model ? `${model.name} (${model.model})` : "",
        };
    }

    // -- compact domain: live match count -----------------------------------
    async _refreshCount() {
        if (this.isAdvancedSource || !this.state.model_name) {
            this.state.matchCount = null;
            return;
        }
        // Parse + count on the server (ast.literal_eval), so a domain value with
        // an apostrophe no longer breaks a client quote-swap and silently counts
        // the whole table. Record rules apply (counted as the current user).
        try {
            this.state.matchCount = await this.orm.call(
                "eh.board.dashboard", "count_domain_matches",
                [this.state.model_name, this.state.domain || "[]",
                 !!this.state.include_archived]);
        } catch (e) {
            this.state.matchCount = null;
        }
    }
    toggleDomain() { this.state.domainOpen = !this.state.domainOpen; }
    onArchivedChange() { this.refreshPreview(); this._refreshCount(); }

    // A plain-English recap of the current config - fills the column floor and
    // doubles as a last read-back before saving.
    measureLabel(measure) {
        const verb = (this.verbs.find((item) => item.key === measure.verb) || {}).label || measure.verb;
        return measure.verb === "count" ? _t("Count") : this.uiText("%s of %s", verb, measure.field || "?");
    }

    get specSummary() {
        const s = this.state;
        if (!this.needsData) return _t("A text block. Whatever you type renders as-is on the board.");
        if (!s.model_id && !s.source_id) return _t("Pick a model or connected source to begin. The preview updates live as you configure.");
        const typeLabel = (this.types.find((t) => t.key === s.item_type) || {}).label || s.item_type;
        const model = this.isAdvancedSource
            ? ((this.selectedSource || {}).name || _t("Connected source"))
            : ((s.models.find((m) => m.id === s.model_id) || {}).name || s.model_name);
        if (this.isRecordList) {
            const labels = s.listFields.map((name) => {
                const field = s.recordFields.find((f) => f.name === name);
                return (field && field.label) || name;
            });
            return labels.length ? _t("A record list of %s showing %s.", model, labels.join(", "))
                : _t("A record list of %s. Choose columns to display.", model);
        }
        const measures = s.measureList.map((m) => {
            if (m.verb === "count") return _t("Record count");
            if (m.verb === "formula") return _t("Calculated value");
            const verb = (this.verbs.find((x) => x.key === m.verb) || {}).label || m.verb;
            return _t("%s of %s", verb, m.field || "?");
        });
        const parts = [_t("%s of %s.", typeLabel, model)];
        if (measures.length && this.needsMeasure) parts.push(_t("Measures: %s.", measures.join(", ")));
        if (this.needsDimension && s.dimension) {
            const dim = (s.dimFields.find((d) => d.name === s.dimension) || {}).label || s.dimension;
            parts.push(_t("Grouped by %s.", dim));
            if (s.secondary_dimension) {
                const d2 = (s.dimFields.find((d) => d.name === s.secondary_dimension) || {}).label
                    || s.secondary_dimension;
                parts.push(_t("Then grouped by %s.", d2));
            }
        }
        if (parseInt(s.record_limit, 10) > 0) parts.push(_t("Top %s records.", s.record_limit));
        if (s.click_action === "records") parts.push(_t("Click a mark to open its records."));
        else if (s.click_action === "drill") parts.push(_t("Click to drill down."));
        return parts.join(" ");
    }

    // -- config changes -----------------------------------------------------
    setTab(tab) { this.state.tab = tab; }
    setType(key) {
        this.state.item_type = key;
        if (key === "todo" && !this.state.content) {
            this.state.content = _t("<p>First task</p><p>Second task</p>");
        }
        if (key === "list" && this.state.list_mode === "records" && !parseInt(this.state.record_limit, 10)) {
            this.state.record_limit = 50;
        }
        if (key === "list" && this.isFixedSource) this.state.list_mode = "grouped";
        if (key === "list" || key === "pivot") this.state.fieldsOpen = true;
        this.refreshPreview();
    }
    onListModeChange() {
        if (this.isRecordList && !parseInt(this.state.record_limit, 10)) {
            this.state.record_limit = 50;
        }
        this.refreshPreview();
    }
    async onModelSelected(records) {
        const record = Array.isArray(records) && records.length ? records[0] : null;
        const modelId = record ? parseInt(record.id, 10) || false : false;
        if (modelId === this.state.model_id) return;
        this.state.model_id = modelId;
        this.state.source_id = false;
        this.state.provider = "orm";
        this.state.dimension = "";
        this.state.secondary_dimension = "";
        this.state.date_field = "";
        this.state.drill_field = "";
        this.state.drillFields = [];
        this.state.window_action_id = false;
        this.state.window_action_name = "";
        this.state.sort_field = "";
        this.state.listFields = [];
        this.state.domain = "[]";
        this.state.dimFields = [];
        this.state.measureFields = [];
        this.state.recordFields = [];
        for (const measure of this.state.measureList) {
            measure.field = "";
            if (measure.verb === "formula") measure.formula = "";
        }
        const m = this.state.models.find((x) => x.id === this.state.model_id);
        this.state.model_name = m ? m.model : "";
        if (this.state.model_id) {
            await this._loadFields(this.state.model_id);
        }
        this.refreshPreview();
        this._refreshCount();
    }
    _resetDataWells() {
        this.state.dimension = "";
        this.state.secondary_dimension = "";
        this.state.date_field = "";
        this.state.drill_field = "";
        this.state.drillFields = [];
        this.state.sort_field = "";
        this.state.listFields = [];
        this.state.dimFields = [];
        this.state.measureFields = [];
        this.state.recordFields = [];
        for (const measure of this.state.measureList) measure.field = "";
    }
    _loadSourceFields(source) {
        this.state.dimFields = [];
        this.state.measureFields = [];
        this.state.recordFields = [];
        if (!source || !(source.tabular || ["file", "rest", "sheets"].includes(source.provider))) return;
        const columns = source.columns || [];
        this.state.dimFields = columns.map((column) => ({
            name: column.name, label: column.label, ttype: column.dtype === "date" ? "date" : column.dtype,
        }));
        this.state.measureFields = columns.filter((column) => column.dtype === "number").map((column) => ({
            name: column.name, label: column.label, ttype: "float",
        }));
        this.state.recordFields = columns.map((column) => ({
            name: column.name, label: column.label, ttype: column.dtype,
        }));
    }
    onSourceSelected(ev) {
        const sourceId = parseInt(ev.target.value, 10) || false;
        this._resetDataWells();
        this.state.source_id = sourceId;
        this.state.model_id = false;
        this.state.model_name = "";
        this.state.window_action_id = false;
        this.state.window_action_name = "";
        const source = this.selectedSource;
        this.state.provider = source ? source.provider : "orm";
        if (!source) {
            this.refreshPreview();
            return;
        }
        this._loadSourceFields(source);
        this.refreshPreview();
    }
    openSourceStudio(sourceId = false) {
        const existing = sourceId && this.state.sources.find((source) => source.id === sourceId);
        if (existing && (["rest", "sheets"].includes(existing.provider) || existing.requires_remote)) {
            this.openRemoteSource(existing.requires_remote || existing.provider, sourceId);
            return;
        }
        const dialogProps = {
            dashboardId: this.props.dashboardId,
            models: this.state.models,
            canSql: this.state.canSql,
            onSaved: (source) => this._connectedSourceSaved(source),
        };
        if (sourceId) dialogProps.sourceId = sourceId;
        this.dialog.add(SourceStudio, dialogProps);
    }
    openRemoteSource(provider = "rest", sourceId = false) {
        if (!this.state.canSql) return;
        const props = {
            dashboardId: this.props.dashboardId,
            provider,
            onSaved: (source) => this._connectedSourceSaved(source),
        };
        if (sourceId) props.sourceId = sourceId;
        this.dialog.add(RemoteSourceDialog, props);
    }
    _connectedSourceSaved(source) {
        if (!source) return;
        const editing = this.state.sources.some((current) => current.id === source.id);
        this.state.sources = editing
            ? this.state.sources.map((current) => current.id === source.id ? source : current)
            : [...this.state.sources, source];
        if (!editing) this._resetDataWells();
        this.state.source_id = source.id;
        this.state.provider = source.provider;
        this.state.model_id = false;
        this.state.model_name = "";
        if (this.isList && ["join", "sql"].includes(source.provider)) this.state.list_mode = "grouped";
        this._loadSourceFields(source);
        this.refreshPreview();
    }
    onField() {
        if (this.isPivot && !this.state.secondary_dimension) {
            for (const measure of this.state.measureList) {
                if (["percent_row", "percent_column"].includes(measure.calculation)) {
                    measure.calculation = "percent_grand";
                }
            }
        }
        this.refreshPreview();
    }
    onContentChange(html) { this.state.content = html; this.refreshPreview(); }
    onDomainChange(domain) {
        // Odoo 17+ hands back a domain string; Odoo 16's DomainSelector hands back
        // a Domain object. Normalise to a string either way.
        this.state.domain = typeof domain === "string"
            ? domain
            : (domain && domain.toString ? domain.toString() : "[]");
        this.refreshPreview();
        this._refreshCount();
    }
    addMeasure() {
        this.state.measureList.push({ verb: "sum", label: "", field: "", format: "compact", unit: "", formula: "", calculation: "none", multiplier: 1, currency_id: false });
        this.refreshPreview();
    }
    onNumberFormat() {
        // The Display "Value format" bulk-sets every measure; a per-measure
        // select in the Data tab can still override an individual one.
        for (const m of this.state.measureList) m.format = this.state.number_format;
        this.refreshPreview();
    }
    get isTargetType() {
        return ["kpi", "tile", "gauge", "bullet"].includes(this.state.item_type);
    }
    get supportsTargetSchedule() {
        return this.isTargetType
            || ["bar", "column", "hbar", "line", "area"].includes(this.state.item_type);
    }
    get supportsComparison() {
        return this.isTargetType || this.isChartType;
    }
    removeMeasure(i) {
        if (this.state.measureList.length > 1) {
            this.state.measureList.splice(i, 1);
            this.refreshPreview();
        }
    }

    addTargetPoint() {
        const today = new Date().toISOString().slice(0, 10);
        this.state.targetSchedule.push({ date: today, value: parseFloat(this.state.target) || 0 });
        this.refreshPreview();
    }
    removeTargetPoint(index) {
        this.state.targetSchedule.splice(index, 1);
        this.refreshPreview();
    }

    async onWindowActionSelected(records) {
        const record = Array.isArray(records) && records.length ? records[0] : null;
        this.state.window_action_id = record ? parseInt(record.id, 10) || false : false;
        this.state.window_action_name = record ? (record.display_name || record.name || "") : "";
        this.refreshPreview();
    }

    get windowActionAutocompleteProps() {
        return {
            activeActions: READONLY_MODEL_ACTIONS,
            fieldString: _t("Odoo action"),
            getDomain: () => [["res_model", "=", this.state.model_name || ""]],
            id: "eh_board_widget_window_action",
            placeholder: _t("Search list, pivot, graph, or kanban action..."),
            quickCreate: null,
            resModel: "ir.actions.act_window",
            searchLimit: 20,
            update: this.onWindowActionSelected.bind(this),
            value: this.state.window_action_name || "",
        };
    }

    // -- fields quick-pick (Power BI Fields list) ---------------------------
    get filteredDims() {
        const q = (this.state.fieldSearch || "").toLowerCase();
        return this.state.dimFields.filter((d) =>
            !q || `${d.label || ""} ${d.name}`.toLowerCase().includes(q));
    }
    get filteredMeasures() {
        const q = (this.state.fieldSearch || "").toLowerCase();
        return this.state.measureFields.filter((m) =>
            !q || `${m.label || ""} ${m.name}`.toLowerCase().includes(q));
    }
    get filteredRecordFields() {
        const q = (this.state.fieldSearch || "").toLowerCase();
        return this.state.recordFields.filter((field) => {
            const haystack = ((field.label || "") + " " + field.name).toLowerCase();
            return !q || haystack.includes(q);
        });
    }
    isListFieldSelected(name) { return this.state.listFields.includes(name); }
    listFieldLabel(name) {
        const field = this.state.recordFields.find((item) => item.name === name);
        return (field && field.label) || name;
    }
    toggleListField(name) {
        const index = this.state.listFields.indexOf(name);
        if (index >= 0) this.state.listFields.splice(index, 1);
        else if (this.state.listFields.length < 12) this.state.listFields.push(name);
        this.refreshPreview();
    }
    pickDimension(name) {
        // Click a field to fill the next empty grouping well: Group by, then Sub.
        if (!this.state.dimension) this.state.dimension = name;
        else if (!this.state.secondary_dimension) this.state.secondary_dimension = name;
        else this.state.dimension = name;
        this.refreshPreview();
    }
    pickMeasure(name) {
        // Drop a numeric field in as a Sum measure (replace a lone Count).
        const list = this.state.measureList;
        if (list.length === 1 && list[0].verb === "count" && !list[0].field) {
            list[0] = { verb: "sum", label: "", field: name, format: "compact", unit: "", formula: "", calculation: "none", multiplier: 1, currency_id: false };
        } else {
            list.push({ verb: "sum", label: "", field: name, format: "compact", unit: "", formula: "", calculation: "none", multiplier: 1, currency_id: false });
        }
        this.refreshPreview();
    }

    // drag a field chip from the panel into a well (Group by / Sub / Measures)
    onFieldDrag(ev, name, kind) {
        ev.dataTransfer.setData("text/plain", JSON.stringify({ name, kind }));
        ev.dataTransfer.effectAllowed = "copy";
    }
    allowDrop(ev) { ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; }
    onWellDrop(ev, target) {
        ev.preventDefault();
        let d;
        try { d = JSON.parse(ev.dataTransfer.getData("text/plain")); } catch (e) { return; }
        if (!d || !d.name) return;
        if (target === "measure") this.pickMeasure(d.name);
        else if (target === "secondary") { this.state.secondary_dimension = d.name; this.refreshPreview(); }
        else this.pickDimension(d.name);
    }

    // -- conditional formatting rules ---------------------------------------
    addRule() {
        this.state.condRules.push({ measure: "", op: "gte", v1: 0, v2: 0, color: "#e8590c", style: "text" });
        this.refreshPreview();
    }
    removeRule(i) {
        this.state.condRules.splice(i, 1);
        this.refreshPreview();
    }

    setCustomColor(index, ev) {
        const value = ev.target.value;
        if (/^#[0-9a-f]{6}$/i.test(value)) {
            this.state.customColors[index] = value;
            this.refreshPreview();
        }
    }

    resetCustomColors() {
        this.state.customColors.splice(0, this.state.customColors.length, ...CUSTOM_COLORS);
        this.refreshPreview();
    }

    addDrillField() {
        const field = this.state.drill_field;
        if (field && !this.state.drillFields.includes(field)
            && this.state.drillFields.length < 8) {
            this.state.drillFields.push(field);
            this.state.drill_field = "";
            this.refreshPreview();
        }
    }
    removeDrillField(index) {
        this.state.drillFields.splice(index, 1);
        this.refreshPreview();
    }

    // -- vals ---------------------------------------------------------------
    _vals() {
        const s = this.state;
        const vals = {
            item_type: s.item_type,
            title: s.title || (this.types.find((t) => t.key === s.item_type) || {}).label || s.item_type,
            accent: s.accent,
            tile_style: s.tile_style,
            show_legend: s.show_legend,
            show_values: s.show_values,
            show_grid: s.show_grid,
            semi_circle: s.semi_circle,
            stacked: s.stacked,
            smooth: s.smooth,
            goal_value: parseFloat(s.goal_value) || 0,
            combo_line: s.combo_line,
            data_label_type: s.data_label_type,
            click_action: s.click_action,
            description: s.description || "",
            conditional_rules: (s.condRules || []).map((r) => ({
                measure: (r.measure === "" || r.measure == null) ? "" : String(r.measure),
                op: r.op, v1: parseFloat(r.v1) || 0, v2: parseFloat(r.v2) || 0,
                color: r.color || "#e8590c", style: r.style || "text",
            })),
            color_mode: s.color_mode || "theme",
            chart_options: {
                ...(s.chartOptions || {}),
                slicer_display: s.slicer_display || "auto",
                series_colors: (s.customColors || []).slice(0, 8).filter(
                    (color) => /^#[0-9a-f]{6}$/i.test(color)),
            },
            show_trend: !!s.show_trend,
        };
        if (this.needsData) {
            vals.model_id = this.isAdvancedSource ? false : s.model_id;
            vals.source_id = this.isAdvancedSource ? s.source_id : false;
            vals.domain = s.domain || "[]";
            vals.include_archived = s.include_archived;
            vals.record_limit_visibility = s.record_limit_visibility;
            vals.list_mode = this.isList ? s.list_mode : "grouped";
            vals.list_fields = this.isRecordList ? s.listFields : [];
            vals.measures = this.isRecordList ? [] : s.measureList.map((m, i) => {
                let calculation = m.calculation || "none";
                if (this.isList && (calculation === "percent_row" || calculation === "percent_column")) {
                    calculation = "percent_grand";
                }
                const spec = {
                    verb: m.verb,
                    label: (m.label || "").trim(),
                    field: (m.verb === "count" || m.verb === "formula") ? null : m.field,
                    number_format: m.format || s.number_format,
                    unit: m.unit || "",
                    formula: m.verb === "formula" ? (m.formula || "0") : "",
                    as_line: !!m.as_line && i > 0,   // combo line only on non-primary
                    table_calculation: this.isTableType ? calculation : "none",
                    multiplier: Number.isFinite(parseFloat(m.multiplier))
                        ? parseFloat(m.multiplier) : 1,
                    currency_id: parseInt(m.currency_id, 10) || false,
                };
                // Target + comparison apply to the primary measure of a KPI-type.
                if (i === 0 && this.isTargetType) {
                    spec.target = parseFloat(s.target) || 0;
                }
                if (i === 0 && this.supportsTargetSchedule) {
                    spec.target_schedule = (s.targetSchedule || []).map((point) => ({
                        date: String(point.date || "").slice(0, 10),
                        value: Number.isFinite(parseFloat(point.value)) ? parseFloat(point.value) : 0,
                    }));
                }
                if (i === 0 && this.supportsComparison) spec.compare_mode = s.compare;
                return spec;
            });
            vals.sort_mode = this.isRecordList ? "field" : s.sort_mode;
            vals.sort_field = this.isRecordList ? s.sort_field
                : (s.sort_mode === "field" ? s.sort_field : "");
            vals.sort_order = s.sort_order;
            vals.record_limit = parseInt(s.record_limit, 10) || 0;
            vals.cumulative = s.cumulative;
            vals.fill_gaps = s.fill_gaps;
            vals.group_others = s.group_others;
            vals.date_field = s.date_field;
            vals.default_date_filter = s.default_date_filter;
            if (s.click_action === "drill") {
                vals.drill_fields = s.drillFields.length
                    ? [...s.drillFields] : (s.drill_field ? [s.drill_field] : []);
            }
            if (s.click_action === "dashboard") {
                vals.target_dashboard_id = parseInt(s.target_dashboard_id, 10) || false;
            } else if (s.click_action === "action") {
                vals.window_action_id = parseInt(s.window_action_id, 10) || false;
            }
            if (this.needsDimension && s.dimension) {
                vals.dimension = s.dimension;
                vals.secondary_dimension = s.secondary_dimension;
                const dim = s.dimFields.find((d) => d.name === s.dimension);
                if (dim && (dim.ttype === "date" || dim.ttype === "datetime")) {
                    vals.granularity = s.granularity;
                }
            }
        } else {
            vals.content = s.content;
        }
        return vals;
    }

    // -- preview ------------------------------------------------------------
    refreshPreview() {
        clearTimeout(this._debounce);
        this._debounce = setTimeout(() => this._doPreview(), 250);
    }
    async _doPreview() {
        this.state.previewing = true;
        try {
            this.state.preview = await this.orm.call(
                "eh.board.dashboard", "preview_item",
                [[this.props.dashboardId], this._vals()]);
        } catch (e) {
            this.state.preview = { meta: null, payload: { error: e.message || String(e) } };
        }
        this.state.previewing = false;
    }
    get previewProps() {
        return {
            meta: this.state.preview.meta || {
                type: this.state.item_type, category: "chart",
                component: this.state.item_type, title: this.state.title,
            },
            payload: this.state.preview.payload,
            editMode: false,
            loading: this.state.previewing,
        };
    }

    // -- confirm ------------------------------------------------------------
    get validationMessage() {
        if (!this.needsData) return "";
        if (!this.state.model_id && !this.state.source_id) {
            return _t("Choose an Odoo model or connected source.");
        }
        if (this.state.click_action === "dashboard" && !this.state.target_dashboard_id) {
            return _t("Choose destination dashboard in Actions.");
        }
        if (this.state.click_action === "action" && !this.state.window_action_id) {
            return _t("Choose Odoo action in Actions.");
        }
        if (this.isFixedSource) {
            if (["slicer", "decomp"].includes(this.state.item_type) || this.isRecordList) {
                return _t("This source returns an aggregated table; choose a chart, KPI, grouped list, or pivot.");
            }
            return "";
        }
        if (this.isRecordList && !this.state.listFields.length) {
            return _t("Pick at least one field to display in the record list.");
        }
        if (this.isRecordList) return "";
        const m = this.state.measureList[0];
        // count needs no field; a formula (calculated) measure uses its formula
        // string, not a field - only value-of-field verbs require a field.
        if (m && m.verb !== "count" && m.verb !== "formula" && !m.field) {
            return _t("Choose a field for first measure.");
        }
        if (m && m.verb === "formula" && !(m.formula || "").trim()) {
            return _t("Enter a calculated-measure formula.");
        }
        if (this.needsDimension && !this.state.dimension) {
            return this.isPivot ? _t("Choose a row field for pivot.") : _t("Choose a field to group by.");
        }
        return "";
    }
    get canConfirm() { return !this.validationMessage; }
    async confirm() {
        const method = this.isEdit ? "update_item_from_builder" : "add_item";
        const args = this.isEdit
            ? [[this.props.dashboardId], this.props.itemId, this._vals()]
            : [[this.props.dashboardId], this._vals()];
        const res = await this.orm.call("eh.board.dashboard", method, args);
        this.props.onSaved(res, this.isEdit);
        this.props.close();
    }
}
