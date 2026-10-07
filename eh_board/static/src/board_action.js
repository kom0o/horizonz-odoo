/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Root client action. Loads the board payload, renders the grid, and owns the
 * view/edit mode, the global date filter, theming, drill and export. State is
 * a plain reactive useState keyed by item id, invalidated surgically on
 * filter/refresh - no global deep-copy churn. */

import { uiText } from "./ui_text";

import { Component, useState, onWillStart, useRef, onMounted, onWillUnmount, useExternalListener } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { BoardGrid } from "./grid";
import { BoardItem } from "./board_item";
import { FilterBar, resolvePreset } from "./filter_bar";
import { AddItemDialog } from "./add_item_dialog";
import { AddFilterDialog } from "./add_filter_dialog";
import { TemplateGallery } from "./template_gallery";
import { InsightsDialog } from "./insights_dialog";
import { DashboardSettings } from "./dashboard_settings";
import { LayoutHistoryDialog } from "./layout_history_dialog";
import { AlertsDialog } from "./alerts_dialog";
import { SmartBuildDialog } from "./smart_build_dialog";
import { AuthoringDialog } from "./authoring_dialog";
import { RemoteSourceDialog } from "./remote_source_dialog";
import { QueryBuilder } from "./query_builder";
import { ScorecardDialog } from "./scorecard_dialog";
import { csvCell, csvRow, payloadTable } from "./csv";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { newOverlayId, useBoardPopover } from "./overlay";
import "./registry";

const THEME_KEY = "eh_board.theme";

export class BoardAction extends Component {
    static template = "eh_board.BoardAction";
    uiText = uiText;
    static components = { BoardGrid, FilterBar, AddItemDialog, BoardItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.rootRef = useRef("root");
        this.exportRef = useRef("exportMenu");
        this.menuRef = useRef("mainMenu");
        this.importRef = useRef("importFile");
        this.BoardItem = BoardItem;

        // Anchored popovers render into one app-level overlay host (overlay.js),
        // outside every scroll container that would otherwise clip them. The id
        // is per-instance so the portal selector can never resolve to another
        // board mounted in the same document.
        this.overlayId = newOverlayId();
        this.overlaySelector = `#${this.overlayId}`;
        this.exportPop = useBoardPopover("exportPop", "exportToggle", {
            align: "end", gap: 6, selector: ".eh_board_export_menu",
        });

        useExternalListener(window, "click", (ev) => {
            // The menu no longer lives inside its trigger wrapper, so a click is
            // "outside" only when it is in neither the wrapper nor the popover.
            if (this.state.exportOpen && this.exportRef.el
                && !this.exportRef.el.contains(ev.target)
                && !this.exportPop.contains(ev.target)) {
                this.state.exportOpen = false;
            }
            if (this.state.menuOpen && this.menuRef.el
                && !this.menuRef.el.contains(ev.target)) {
                this.state.menuOpen = false;
            }
        });
        useExternalListener(window, "keydown", (ev) => {
            // Escape dismisses an open popover first: outside Present mode the
            // handler below returns early, so neither had any keyboard exit.
            if (ev.key === "Escape" && !this.state.kiosk
                && (this.state.exportOpen || this.state.menuOpen)) {
                this.state.exportOpen = false;
                this.state.menuOpen = false;
                return;
            }
            if (!this.state.kiosk) return;
            if (ev.key === "Escape") this._exitPresent();
            else if (ev.key === "ArrowRight") this.nextSlide();
            else if (ev.key === "ArrowLeft") this.prevSlide();
            else if (ev.key === " ") { ev.preventDefault(); this.togglePlay(); }
        });
        // The browser can leave fullscreen on its own (Esc, gesture, focus loss);
        // reconcile our state so the full header always comes back.
        useExternalListener(document, "fullscreenchange", () => {
            if (!document.fullscreenElement && this.state.kiosk) this._exitPresent();
        });
        this._kioskTimer = null;
        this._prePresent = null;
        // Monotonic tokens so an out-of-order RPC response (rapid filter/board
        // switches, or a poll colliding with a filter change) can never paint the
        // board with numbers for a state the user has already moved off.
        this._loadToken = 0;
        this._refreshToken = 0;
        // Layout snapshot for Discard: taken once per edit session, from whichever
        // path enters edit mode (not only the toolbar toggle).
        this._editSnapshotTaken = false;
        this._lazyRetries = {};
        this._lazyTimers = [];   // pending lazy-retry timeouts, cleared on unmount

        this.state = useState({
            loading: true,
            dashboardId: this._paramId(),
            name: "",
            metas: [],
            payloads: {},
            grid: {},
            filters: [],
            mode: "view",
            preset: "all",
            customStart: "",
            customEnd: "",
            filterValues: {},
            theme: browserTheme(),
            loadingIds: {},
            exportOpen: false,
            boards: [],
            navigation: [],
            favorite: false,
            lazyIds: {},
            menuOpen: false,
            editor: { open: false, itemId: null },
            kiosk: false,
            autoRotate: true,
            rotateSecs: 12,
            slides: [],
            slideIdx: 0,
            playing: true,
            palette: "default",
            crossfilter: false,
            crossFilters: [],
            drillStacks: {},
            density: "comfortable",
            refreshMode: "off",
            refreshInterval: 60,
            canEdit: false,
            canRemote: false,
            error: null,
        });

        onWillStart(() => this.loadData());
        onMounted(() => { this._applyTheme(); this._applyDensity(); });
        this._refreshTimer = null;
        onWillUnmount(() => {
            this._clearTimer();
            document.documentElement.removeAttribute("data-eh-board-theme");
            if (this._kioskTimer) browser().clearInterval(this._kioskTimer);
            // Cancel any pending lazy-retry timeouts so none fires on a destroyed
            // component (a leak / setState-after-unmount).
            this._lazyTimers.forEach((t) => browser().clearTimeout(t));
            this._lazyTimers = [];
        });
    }

    _paramId() {
        const p = this.props.action && this.props.action.params;
        return (p && p.dashboard_id) || (this.props.action && this.props.action.context
            && this.props.action.context.dashboard_id) || null;
    }

    _kioskRequested() {
        return new URLSearchParams(browser().location.search).get("kiosk") === "1";
    }

    get options() {
        const opts = {};
        const range = this.state.preset === "custom"
            ? (this.state.customStart && this.state.customEnd
                && this.state.customStart <= this.state.customEnd
                ? { start: this.state.customStart, end: this.state.customEnd } : null)
            : resolvePreset(this.state.preset);
        if (range) opts.date_range = range;
        // Merge only filters with same semantic identity. Technical names alone
        // are unsafe: sale.order.state != account.move.state. Cross-filter reuses
        // the exact same server plumbing as a global filter - clicking a mark is
        // just another way to narrow every widget at once.
        const byField = {};
        for (const f of (this.state.filters || [])) {
            const vals = this.state.filterValues[f.id];
            if (f.type === "field" && vals && vals.length) {
                const key = ["", f.model || "", f.relation || "", f.field].join("|");
                const entry = byField[key] || {
                    field: f.field, model: f.model, relation: f.relation, values: new Set(),
                };
                vals.forEach((v) => entry.values.add(v));
                byField[key] = entry;
            }
        }
        for (const c of (this.state.crossFilters || [])) {
            const key = [c.sourceId || "", c.model || "", c.relation || "", c.field].join("|");
            const entry = byField[key] || {
                field: c.field, model: c.model, relation: c.relation, source_id: c.sourceId, values: new Set(),
            };
            entry.values.add(c.value);
            byField[key] = entry;
        }
        const filters = Object.values(byField).map((entry) => ({
            field: entry.field, model: entry.model, relation: entry.relation,
            source_id: entry.source_id,
            values: [...entry.values],
        }));
        if (filters.length) opts.filters = filters;
        return opts;
    }

    async loadData() {
        const token = ++this._loadToken;
        // A fresh board load starts a fresh edit session, and a fresh lazy-retry
        // budget (so a widget that failed on a previous board still gets retries).
        this._editSnapshotTaken = false;
        this._lazyRetries = {};
        this._lazyTimers.forEach((t) => browser().clearTimeout(t));
        this._lazyTimers = [];
        this.state.loading = true;
        try {
            let id = this.state.dashboardId;
            if (!id) {
                const first = await this.orm.search(
                    "eh.board.dashboard", [], { limit: 1 });
                id = first.length ? first[0] : null;
                this.state.dashboardId = id;
            }
            if (!id) {
                this.state.canEdit = !!(await this.orm.call(
                    "eh.board.dashboard", "can_build", [[]]));
                this.state.error = _t("No dashboard yet. Create one from the Dashboards menu.");
                this.state.loading = false;
                return;
            }
            const data = await this.orm.call(
                "eh.board.dashboard", "get_data", [[id], this.options, true]);
            // A newer load started while this one was in flight (fast board
            // switch): drop this stale result so the newest board wins.
            if (token !== this._loadToken) return;
            this.state.name = data.name;
            this.state.grid = data.layout || {};
            this.state.filters = data.filters || [];
            const defaults = {};
            let appliedDefaults = false;
            for (const filter of this.state.filters) {
                const value = filter.default || {};
                if (filter.type === "field" && Array.isArray(value.values)
                    && value.values.length) {
                    defaults[filter.id] = [...value.values];
                }
            }
            // Preserve live choices during refresh; initialise defaults on a
            // fresh board switch only (pickBoard clears filterValues first).
            if (!Object.keys(this.state.filterValues || {}).length) {
                this.state.filterValues = defaults;
                appliedDefaults = Object.keys(defaults).length > 0;
            }
            this.state.metas = data.item_meta || [];
            this.state.density = data.density || "comfortable";
            this.state.palette = data.palette || "default";
            this.state.refreshMode = data.refresh_mode || "off";
            this.state.refreshInterval = data.refresh_interval || 60;
            this.state.canEdit = !!data.can_edit;
            this.state.canRemote = !!data.can_remote;
            this.state.favorite = !!data.is_favorite;
            this.state.navigation = data.navigation || [];
            // Open on the board's configured default date range (falls back to
            // "None" = all time).
            this.state.preset = data.default_date_preset || "all";
            if (this.state.preset === "all") {
                const dateFilter = this.state.filters.find((f) => f.type === "date");
                if (dateFilter) {
                    this.state.preset = (dateFilter.default && dateFilter.default.preset)
                        || dateFilter.date_preset || "all";
                }
            }
            this.state.payloads = {};
            for (const p of data.items || []) {
                this.state.payloads[p.id] = p;
            }
            // Deferred widgets: mark loading; fetched as they scroll into view.
            this.state.lazyIds = {};
            for (const lid of data.lazy_ids || []) {
                this.state.lazyIds[lid] = true;
                this.state.loadingIds[lid] = true;
            }
            this.state.error = null;
            this.loadBoardList();
            if (appliedDefaults) this.refreshItems();
            if (data.is_kiosk && this._kioskRequested() && !this.state.kiosk) {
                browser().setTimeout(() => this._enterPresent(), 0);
            }
        } catch (e) {
            this.state.error = e.message || String(e);
        }
        this.state.loading = false;
        this._applyDensity();
        this._scheduleRefresh();
    }

    async refreshItems() {
        const id = this.state.dashboardId;
        if (!id) return;
        // Stamp this refresh: a later filter/cross-filter change (or a poll that
        // races a filter change) bumps the token, and any response from an older
        // refresh is discarded instead of painting stale numbers under the new
        // filter state.
        const token = ++this._refreshToken;
        // Drilled widgets refetch at their current level so a filter change or
        // auto-refresh re-scopes the drill instead of collapsing it.
        const normal = [], drilled = [];
        for (const m of this.state.metas) {
            ((this.state.drillStacks[m.id] || []).length ? drilled : normal).push(m.id);
        }
        const touched = [...normal, ...drilled];
        touched.forEach((i) => (this.state.loadingIds[i] = true));
        try {
            if (normal.length) {
                const items = await this.orm.call(
                    "eh.board.dashboard", "get_item_data", [[id], normal, this.options]);
                if (token !== this._refreshToken) return;
                for (const p of items) this.state.payloads[p.id] = p;
            }
            for (const did of drilled) {
                const p = await this.orm.call("eh.board.dashboard", "get_item_drilled",
                    [[id], did, this.state.drillStacks[did], this.options]);
                if (token !== this._refreshToken) return;
                this.state.payloads[did] = p;
            }
        } finally {
            // Clear every touched id - even ones the server dropped or a failed
            // poll - so a refresh error can never leave widgets skeletonized. Only
            // the latest refresh owns the loading flags.
            if (token === this._refreshToken) {
                touched.forEach((i) => (this.state.loadingIds[i] = false));
            }
        }
    }

    // -- main menu ----------------------------------------------------------
    toggleMenu() {
        this.state.menuOpen = !this.state.menuOpen;
    }
    goHome() {
        // Always-available route back to the Odoo apps so a full-bleed board is
        // never a dead end.
        this.state.menuOpen = false;
        browser().location.assign("/odoo");
    }
    async newDashboard() {
        if (!this.state.canEdit) return;
        this.state.menuOpen = false;
        const res = await this.orm.create(
            "eh.board.dashboard", [{ name: _t("New dashboard"), state: "draft" }]);
        const id = Array.isArray(res) ? res[0] : res;
        this.state.dashboardId = id;
        this.state.drillStacks = {};
        this.state.crossFilters = [];
        this.state.filterValues = {};
        this.state.customStart = "";
        this.state.customEnd = "";
        await this.loadData();
        this._enterEdit();
    }
    pickBoard(id) {
        this.state.menuOpen = false;
        if (id === this.state.dashboardId) return;
        this.state.dashboardId = id;
        this.state.drillStacks = {};
        this.state.crossFilters = [];
        this.state.filterValues = {};
        this.state.preset = "all";
        this.state.customStart = "";
        this.state.customEnd = "";
        this.loadData();
    }
    async toggleFavorite() {
        const result = await this.orm.call(
            "eh.board.dashboard", "toggle_favorite", [[this.state.dashboardId]]);
        this.state.favorite = !!(result && result.favorite);
        await this.loadBoardList();
    }

    // -- presentation mode --------------------------------------------------
    // "Play" is a real slideshow: a full-viewport overlay spotlights one widget
    // at a time, large and centred, auto-advancing with play/pause + prev/next +
    // progress. Fullscreen is requested on the document root (not the leaf app)
    // so the Odoo navbar stays inside the fullscreen subtree and the user is
    // never trapped. Exiting by ANY route restores the exact prior mode.
    toggleKiosk() {
        if (this.state.kiosk) this._exitPresent();
        else this._enterPresent();
    }
    _enterPresent() {
        this._prePresent = { mode: this.state.mode };
        this._buildSlides();
        this.state.slideIdx = 0;
        // Stop the auto-refresh poll while presenting: a failed poll must not
        // flip the spotlighted slide to a skeleton, and the slide timer owns
        // pacing here. Re-armed on exit.
        this._clearTimer();
        this._preloadPresent();   // no blank slide: fetch any still-deferred widgets
        this.state.playing = this.state.autoRotate;
        this.state.kiosk = true;
        this.state.mode = "view";
        this.state.menuOpen = false;
        this.state.exportOpen = false;
        const el = browser().document.documentElement;
        if (el && el.requestFullscreen) el.requestFullscreen().catch(() => {});
        if (this.state.playing) this._startSlideTimer();
    }
    _exitPresent() {
        this.state.kiosk = false;
        this._stopSlideTimer();
        if (browser().document.fullscreenElement && browser().document.exitFullscreen) {
            browser().document.exitFullscreen().catch(() => {});
        }
        // Restore the mode we came from so the full header returns intact.
        if (this._prePresent) {
            this.state.mode = this._prePresent.mode;
            this._prePresent = null;
        }
        this._scheduleRefresh();   // re-arm the auto-refresh poll paused on enter
    }
    _buildSlides() {
        // One slide per widget on the current board; content/text tiles included
        // so a narrated board reads end to end.
        this.state.slides = this.state.metas.map((m) => m.id);
    }
    get currentSlide() {
        const id = this.state.slides[this.state.slideIdx];
        return this.state.metas.find((m) => m.id === id) || null;
    }
    get presentPosition() {
        return (this.state.slides.length ? this.state.slideIdx + 1 : 0)
            + " / " + this.state.slides.length;
    }
    nextSlide() { this._goSlide(1); }
    prevSlide() { this._goSlide(-1); }
    goToSlide(i) {
        this.state.slideIdx = i;
        this._fetchLazy(this.state.slides[i]);   // load on demand if still deferred
        if (this.state.playing) this._startSlideTimer();
    }
    _goSlide(dir) {
        const n = this.state.slides.length;
        if (!n) return;
        this.state.slideIdx = (this.state.slideIdx + dir + n) % n;
        this._fetchLazy(this.state.slides[this.state.slideIdx]);
        if (this.state.playing) this._startSlideTimer();  // reset dwell after a manual step
    }
    togglePlay() {
        this.state.playing = !this.state.playing;
        if (this.state.playing) this._startSlideTimer();
        else this._stopSlideTimer();
    }
    toggleAutoRotate() { this.togglePlay(); }
    _startSlideTimer() {
        this._stopSlideTimer();
        if (this.state.slides.length > 1) {
            this._kioskTimer = browser().setInterval(
                () => this.nextSlide(), this.state.rotateSecs * 1000);
        }
    }
    _stopSlideTimer() {
        if (this._kioskTimer) {
            browser().clearInterval(this._kioskTimer);
            this._kioskTimer = null;
        }
    }

    // -- switcher + lazy load ----------------------------------------------
    async loadBoardList() {
        try {
            this.state.boards = await this.orm.call(
                "eh.board.dashboard", "list_boards", [[]]);
        } catch (e) {
            this.state.boards = [];
        }
    }
    switchTo(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.dashboardId) return;
        this.state.dashboardId = id;
        this.state.drillStacks = {};
        this.state.crossFilters = [];
        this.state.filterValues = {};
        this.state.preset = "all";
        this.state.customStart = "";
        this.state.customEnd = "";
        this.loadData();
    }
    async onVisible(itemId) {
        // A deferred widget scrolled into view: fetch just this one.
        return this._fetchLazy(itemId);
    }

    async _fetchLazy(itemId) {
        // Fetch one still-deferred widget. Idempotent: the lazyIds guard makes a
        // second call (e.g. the grid observer AND the presentation preload both
        // firing) a no-op, so a widget is never fetched twice.
        if (!itemId || !this.state.lazyIds[itemId]) return;
        delete this.state.lazyIds[itemId];
        this.state.loadingIds[itemId] = true;
        try {
            const arr = await this.orm.call("eh.board.dashboard", "get_item_data",
                [[this.state.dashboardId], [itemId], this.options]);
            if (arr && arr[0]) {
                this.state.payloads[itemId] = arr[0];
            } else {
                // The item was removed or rule-filtered server-side between load
                // and fetch: show a clear message, never a blank/degenerate chart.
                this.state.payloads[itemId] = {
                    id: itemId, error: _t("This widget is no longer available.") };
            }
        } catch (e) {
            // Transport / session / access failure. Re-arm lazy so presentation
            // preload retries, but the grid observer unobserves after the first
            // intersection, so on a normal board a scroll never retries - schedule
            // a bounded auto-retry (up to 2) so a transient blip does not strand
            // the widget blank forever.
            this.state.lazyIds[itemId] = true;
            const tries = (this._lazyRetries[itemId] || 0) + 1;
            this._lazyRetries[itemId] = tries;
            if (tries <= 2) {
                this._lazyTimers.push(
                    browser().setTimeout(() => this._fetchLazy(itemId), 4000 * tries));
            } else {
                this.state.payloads[itemId] = {
                    id: itemId, error: _t("This widget could not be loaded. Refresh to retry.") };
                delete this.state.lazyIds[itemId];
            }
        } finally {
            // Always clear loading so the skeleton can never stick forever.
            this.state.loadingIds[itemId] = false;
        }
    }

    _preloadPresent() {
        // A slideshow spotlights EVERY widget one at a time, but the grid's
        // IntersectionObserver never fires inside the presentation overlay, so a
        // still-deferred widget would show its loading skeleton forever. Eager
        // fetch every lazy slide (the current one first) when presentation opens.
        const cur = this.state.slides[this.state.slideIdx];
        if (cur) this._fetchLazy(cur);
        for (const id of this.state.slides) this._fetchLazy(id);
    }

    // -- filter -------------------------------------------------------------
    onPresetChange(preset) {
        this.state.preset = preset;
        this.refreshItems();
    }
    onCustomDateChange(start, end) {
        this.state.customStart = start || "";
        this.state.customEnd = end || "";
        if (this.state.preset === "custom" && start && end && start <= end) {
            this.refreshItems();
        }
    }
    onFilterChange(filterId, values) {
        this.state.filterValues[filterId] = values;
        this.refreshItems();
    }
    openAddFilter() {
        this._enterEdit();
        this.dialog.add(AddFilterDialog, {
            dashboardId: this.state.dashboardId,
            onAdded: (filter) => {
                this.state.filters = [...this.state.filters, filter];
                this.notification.add(_t("Filter added."), { type: "success" });
            },
        });
    }

    // -- mode ---------------------------------------------------------------
    /** Snapshot the current layout the first time this edit session enters edit
     *  mode, so Discard reverts this session's changes no matter which control
     *  (toolbar, add widget, configure, add filter) opened the editor. */
    _enterEdit() {
        if (!this.state.canEdit) return;
        if (!this._editSnapshotTaken) {
            this._editGrid = JSON.parse(JSON.stringify(this.state.grid || {}));
            this._editDensity = this.state.density;
            this._editSnapshotTaken = true;
        }
        this.state.mode = "edit";
    }
    async toggleMode() {
        if (this.state.mode !== "edit") {
            this._enterEdit();
        } else {
            if (this._editSnapshotTaken) {
                await this.orm.call("eh.board.dashboard", "commit_layout", [
                    [this.state.dashboardId], this._editGrid || {},
                    this._editDensity || "comfortable",
                ]);
            }
            this.state.mode = "view";
            this._editSnapshotTaken = false;
        }
    }
    async discardEdits() {
        // Revert the arrangement to how it was when editing started, then leave
        // edit mode. Deletions are already confirmed, so nothing is lost here.
        if (this._editSnapshotTaken && this._editGrid) {
            this.state.grid = JSON.parse(JSON.stringify(this._editGrid));
            this.state.density = this._editDensity || "comfortable";
            this._applyDensity();
            await this.orm.call("eh.board.dashboard", "save_layout",
                [[this.state.dashboardId], this.state.grid, this.state.density]);
        }
        this.state.mode = "view";
        this._editSnapshotTaken = false;
        this.notification.add(_t("Changes discarded."), { type: "info" });
    }
    get editMode() {
        return this.state.mode === "edit";
    }

    // -- theme --------------------------------------------------------------
    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        browser().localStorage.setItem(THEME_KEY, this.state.theme);
        this._applyTheme();
    }
    _applyTheme() {
        if (this.rootRef.el) {
            this.rootRef.el.setAttribute("data-eh-theme", this.state.theme);
            this.rootRef.el.setAttribute("data-eh-palette", this.state.palette);
        }
        // OWL dialogs render in portal outside app root. Mirror theme onto html
        // so builder/settings/insights inherit readable tokens in dark mode.
        document.documentElement.setAttribute("data-eh-board-theme", this.state.theme);
    }
    async setPalette(ev) {
        this.state.palette = ev.target.value;
        this._applyTheme();
        await this.orm.call("eh.board.dashboard", "save_settings",
            [[this.state.dashboardId], { palette: this.state.palette }]);
    }

    // -- cross-filter -------------------------------------------------------
    toggleCrossfilter() {
        this.state.crossfilter = !this.state.crossfilter;
        if (!this.state.crossfilter && this.state.crossFilters.length) {
            this.clearCrossFilters();
        }
    }
    toggleCrossFilter(field, value, label, model = null, relation = null, sourceId = null) {
        const key = [sourceId || "", model || "", relation || "", field, String(value)].join(":");
        const i = this.state.crossFilters.findIndex((c) => c.key === key);
        if (i >= 0) {
            this.state.crossFilters.splice(i, 1);
        } else {
            this.state.crossFilters = [
                ...this.state.crossFilters, { key, field, value, label, model, relation, sourceId }];
        }
        this.refreshItems();
    }
    removeCrossFilter(key) {
        this.state.crossFilters = this.state.crossFilters.filter((c) => c.key !== key);
        this.refreshItems();
    }
    clearCrossFilters() {
        if (!this.state.crossFilters.length) return;
        this.state.crossFilters = [];
        this.refreshItems();
    }

    // -- density ------------------------------------------------------------
    async toggleDensity() {
        this.state.density = this.state.density === "compact" ? "comfortable" : "compact";
        this._applyDensity();
        await this.orm.call("eh.board.dashboard", "save_layout",
            [[this.state.dashboardId], this.state.grid, this.state.density]);
    }
    _applyDensity() {
        if (this.rootRef.el) {
            this.rootRef.el.setAttribute("data-eh-density", this.state.density);
        }
    }

    // -- layout -------------------------------------------------------------
    async onLayoutChange(grid) {
        this.state.grid = grid;
        await this.orm.call("eh.board.dashboard", "save_layout",
            [[this.state.dashboardId], grid]);
    }

    // -- insights -----------------------------------------------------------
    openInsights() {
        this.dialog.add(InsightsDialog, {
            dashboardId: this.state.dashboardId, options: this.analysisOptions,
        });
    }

    // -- dashboard settings -------------------------------------------------
    openSettings() {
        this.state.menuOpen = false;
        this.dialog.add(DashboardSettings, {
            dashboardId: this.state.dashboardId,
            onSaved: (s) => this._applySettings(s),
        });
    }
    openLayoutHistory() {
        this.dialog.add(LayoutHistoryDialog, {
            dashboardId: this.state.dashboardId,
            canEdit: this.state.canEdit,
            onRestored: (result) => {
                this.state.grid = result.grid || {};
                this.state.density = result.density || "comfortable";
                this._applyDensity();
                this.notification.add(_t("Layout restored."), { type: "success" });
            },
        });
    }
    openAlerts() {
        this.state.menuOpen = false;
        this.dialog.add(AlertsDialog, { dashboardId: this.state.dashboardId });
    }
    _applySettings(s) {
        // Apply the visible changes without a full reload so any active drill /
        // cross-filter survives; re-arm the refresh timer for the new cadence.
        this.state.name = s.name;
        this.state.palette = s.palette;
        this.state.density = s.density;
        this.state.refreshMode = s.refresh_mode;
        this.state.refreshInterval = s.refresh_interval;
        this._applyTheme();
        this._applyDensity();
        this._scheduleRefresh();
        this.notification.add(_t("Dashboard settings saved."), { type: "success" });
        this.loadData();
    }

    // -- templates ----------------------------------------------------------
    async openAuthoring() {
        if (!this.state.canEdit) return;
        await this._ensureBoard();
        this.state.menuOpen = false;
        this.dialog.add(AuthoringDialog, {
            dashboardId: this.state.dashboardId,
            onSaved: async () => {
                await this.loadData();
                this._enterEdit();
                this.notification.add(_t("Selected AI widgets added."), { type: "success" });
            },
        });
    }
    async openQueryBuilder() {
        if (!this.state.canEdit) return;
        await this._ensureBoard();
        this.state.menuOpen = false;
        this.dialog.add(QueryBuilder, {
            dashboardId: this.state.dashboardId,
            onSaved: async () => {
                await this.loadData();
                this._enterEdit();
                this.notification.add(_t("Query widget added."), { type: "success" });
            },
        });
    }
    openScorecard() {
        if (!this.state.dashboardId) return;
        this.state.menuOpen = false;
        this.dialog.add(ScorecardDialog, {
            dashboardId: this.state.dashboardId,
            options: this.analysisOptions,
        });
    }
    async openRemoteSources() {
        if (!this.state.canRemote) return;
        await this._ensureBoard();
        this.state.menuOpen = false;
        this.dialog.add(RemoteSourceDialog, {
            dashboardId: this.state.dashboardId,
            onSaved: async () => {
                await this.loadData();
                this.notification.add(_t("Remote source saved. Choose it when adding a widget."), { type: "success" });
            },
        });
    }
    async saveDigestView() {
        this.state.menuOpen = false;
        await this.orm.call("eh.board.dashboard", "save_digest_view",
            [[this.state.dashboardId], this.analysisOptions, this.state.preset]);
        this.notification.add(_t("Current filters saved for scheduled digests. Relative dates advance automatically."), { type: "success" });
    }
    openTemplates() {
        this.dialog.add(TemplateGallery, { dashboardId: this.state.dashboardId });
    }
    async openSmartBuild() {
        if (!this.state.canEdit) return;
        await this._ensureBoard();
        this.state.menuOpen = false;
        this.dialog.add(SmartBuildDialog, {
            dashboardId: this.state.dashboardId,
            hasItems: !!this.state.metas.length,
            onBuilt: async (result) => {
                await this.loadData();
                this._enterEdit();
                this.notification.add(
                    _t("Smart Build created %s widgets for %s.")
                        .replace("%s", result.created || 0)
                        .replace("%s", result.model || _t("selected model")),
                    { type: "success" });
            },
        });
    }
    async saveAsTemplate() {
        const res = await this.orm.call("eh.board.dashboard", "save_as_template",
            [[this.state.dashboardId]]);
        if (res && res.template_id) {
            this.notification.add(
                _t("Saved as a reusable template."), { type: "success" });
        }
    }

    // -- add / edit item (full-screen editor, not a modal) ------------------
    async _ensureBoard() {
        // A widget's dashboard_id is required, so there must be a PERSISTED board
        // before one can be added. On a fresh install (no board yet) create one
        // first, so add_item never runs against a null/unsaved dashboard id.
        if (this.state.dashboardId) return this.state.dashboardId;
        const res = await this.orm.create(
            "eh.board.dashboard", [{ name: _t("New dashboard"), state: "draft" }]);
        const id = Array.isArray(res) ? res[0] : res;
        this.state.dashboardId = id;
        await this.loadData();
        return id;
    }
    async openAddDialog() {
        if (!this.state.canEdit) return;
        await this._ensureBoard();
        this._enterEdit();
        this.state.menuOpen = false;
        this.state.editor = { open: true, itemId: null };
    }
    closeEditor() {
        this.state.editor = { open: false, itemId: null };
    }
    onEditorSaved(res, isEdit) {
        this._onSaved(res, isEdit);
        this.closeEditor();
    }
    _onSaved(res, isEdit) {
        if (!res || !res.meta) return;
        if (isEdit) {
            this.state.metas = this.state.metas.map((m) => (m.id === res.meta.id ? res.meta : m));
            this.notification.add(_t("Widget updated."), { type: "success" });
        } else {
            this.state.metas = [...this.state.metas, res.meta];
            this._placeNewItem(res.meta);
            this.notification.add(_t("Widget added."), { type: "success" });
        }
        this.state.payloads[res.meta.id] = res.payload;
    }

    /** Park a newly added/duplicated card in a free row at the bottom. The
     *  server geometry defaults to (0,0), so without this every new widget
     *  would stack on top of an existing one. */
    _placeNewItem(meta) {
        let maxY = 0;
        for (const g of Object.values(this.state.grid || {})) {
            maxY = Math.max(maxY, (g.y || 0) + (g.h || 4));
        }
        const geo = meta.geometry || {};
        this.state.grid[String(meta.id)] = {
            x: 0, y: maxY, w: geo.w || 4, h: geo.h || 6,
        };
        this.orm.call("eh.board.dashboard", "save_layout",
            [[this.state.dashboardId], this.state.grid, this.state.density]).catch(() => {});
    }
    removeItem(meta) {
        // Never delete on a single click - confirm first (non-technical users).
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete widget"),
            body: _t('Delete "%s"? This cannot be undone.', meta.title || meta.type),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            cancelLabel: _t("Keep it"),
            confirm: () => this._doRemoveItem(meta),
            cancel: () => {},
        });
    }
    async _doRemoveItem(meta) {
        await this.orm.call("eh.board.dashboard", "delete_item",
            [[this.state.dashboardId], meta.id]);
        this.state.metas = this.state.metas.filter((m) => m.id !== meta.id);
        delete this.state.payloads[meta.id];
        this.notification.add(_t("Widget deleted."), { type: "success" });
    }
    async duplicateItem(meta) {
        const res = await this.orm.call("eh.board.dashboard", "duplicate_item",
            [[this.state.dashboardId], meta.id]);
        if (res && res.meta) {
            this.state.metas = [...this.state.metas, res.meta];
            this._placeNewItem(res.meta);
            this.state.payloads[res.meta.id] = res.payload;
            this.notification.add(_t("Widget duplicated."), { type: "success" });
        }
    }

    // -- drill --------------------------------------------------------------
    onDrill(meta, info) {
        // A slicer chip toggles a board-wide cross-filter (sync slicer).
        if (info && info.slice) {
            this.toggleCrossFilter(info.slice.field, info.slice.value, info.slice.label,
                info.slice.model || meta.model, info.slice.relation || meta.dimension_relation);
            return;
        }
        if (meta.click_action === "dashboard") {
            if (meta.target_dashboard_id) this.pickBoard(meta.target_dashboard_id);
            else this.notification.add(
                _t("Destination dashboard is no longer available."), { type: "warning" });
            return;
        }
        // Click a bar/slice/point -> open the underlying records, scoped to the
        // clicked group (exact value, or a period range for a date bucket).
        const payload = this.state.payloads[meta.id];
        if (!payload || (!meta.model && !meta.source_id)) {
            this.notification.add(
                _t("Drill-down needs a data source on this widget."), { type: "warning" });
            return;
        }
        // Cross-filter mode: clicking a categorical mark toggles a board-wide
        // filter on that value instead of opening records - the defining BI
        // gesture (click a region, every widget re-scopes to it).
        if (this.state.crossfilter && info && !info.domain && meta.dimension
            && meta.dimension_type !== "date" && meta.dimension_type !== "datetime") {
            const row = payload.rows && typeof info.index === "number"
                ? payload.rows[info.index] : null;
            if (row && row.keys && row.keys.length) {
                let key = row.keys[0];
                // A boolean False group arrives as a null key (False collapses to
                // "no value" upstream). For a boolean dimension that null IS the
                // real, filterable value False, so map it back - otherwise the
                // False (e.g. "individuals") bar is inert and never cross-filters.
                if (meta.dimension_type === "boolean" && (key === null || key === undefined)) {
                    key = false;
                }
                if (key !== null && key !== undefined) {
                    this.toggleCrossFilter(meta.dimension, key,
                        info.label || (row.labels && row.labels[0]) || String(key),
                        meta.model, meta.dimension_relation, meta.source_id);
                    return;
                }
            }
        }
        // Drill down a level: regroup THIS widget by the next configured field,
        // scoped to the clicked value, leaving a breadcrumb to climb back.
        if (meta.click_action === "drill" && meta.has_drill
            && info && !info.domain && typeof info.index === "number") {
            this._drillInto(meta, info);
            return;
        }
        // Explicitly click-inert widgets do nothing (but still cross-filter /
        // drill above when configured for it).
        if (meta.click_action === "none" || !meta.model) return;
        // Every click-through starts from the widget's own static scope so a
        // tile or a bar opens exactly the records behind it, never the whole
        // model. A ready-built domain (e.g. the pivot) layers on top.
        const base = (payload.effective_domain || meta.base_domain || [])
            .map((l) => Array.isArray(l) ? [...l] : l);
        if (info && info.domain) {
            this._openRecords(meta, base.concat(info.domain), info.label);
            return;
        }
        const domain = base;
        const row = payload.rows && info ? payload.rows[info.index] : null;
        const field = meta.dimension;
        if (field && row && row.keys && row.keys.length) {
            const key = row.keys[0];
            if (meta.dimension_type === "date" || meta.dimension_type === "datetime") {
                const range = periodRange(key, meta.granularity);
                if (range) domain.push([field, ">=", range.start], [field, "<", range.end]);
            } else if (key === null || key === false) {
                domain.push([field, "=", false]);
            } else {
                domain.push([field, "=", key]);
            }
        }
        this._openRecords(meta, domain, info && info.label);
    }

    _openRecords(meta, domain, label) {
        if (meta.click_action === "action") {
            this._openConfiguredAction(meta, domain, label);
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: (meta.title || _t("Records")) + (label ? " · " + label : ""),
            res_model: meta.model,
            domain: domain || [],
            views: [[false, "list"], [false, "form"]],
            target: "current",
            limit: meta.record_limit_visibility && meta.record_limit
                ? meta.record_limit : undefined,
        }).catch(() => this.notification.add(
            _t("Could not open records for this widget."), { type: "warning" }));
    }

    async _openConfiguredAction(meta, domain, label) {
        try {
            const action = await this.orm.call(
                "eh.board.dashboard", "get_item_window_action",
                [[this.state.dashboardId], meta.id, domain || [], label || ""]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(
                error.message || _t("Could not open configured Odoo action."),
                { type: "warning" });
        }
    }

    async _drillInto(meta, info) {
        const payload = this.state.payloads[meta.id];
        const row = payload && payload.rows ? payload.rows[info.index] : null;
        if (!row || !row.keys || !row.keys.length) return;
        const stack = this.state.drillStacks[meta.id] || [];
        const depth = stack.length;
        const chain = meta.drill || [];
        // Field grouped at the current depth: the widget's own dimension at the
        // top, then each drill step's field.
        const field = depth === 0 ? meta.dimension : (chain[depth - 1] && chain[depth - 1].field);
        if (!field) return;
        const next = [...stack, {
            field, value: row.keys[0],
            label: info.label || (row.labels && row.labels[0]) || String(row.keys[0]),
        }];
        if (next.length > chain.length) {
            // No deeper level configured -> open the records at this slice.
            const base = (payload.effective_domain || meta.base_domain || [])
                .map((leaf) => Array.isArray(leaf) ? [...leaf] : leaf);
            const domain = base.concat(next.map((p) => [p.field, "=",
                (p.value === null || p.value === false) ? false : p.value]));
            this._openRecords(meta, domain, info.label);
            return;
        }
        this.state.drillStacks = { ...this.state.drillStacks, [meta.id]: next };
        this.state.loadingIds[meta.id] = true;
        try {
            const p = await this.orm.call("eh.board.dashboard", "get_item_drilled",
                [[this.state.dashboardId], meta.id, next, this.options]);
            this.state.payloads[meta.id] = p;
        } catch (e) {
            // Roll the breadcrumb back so the widget stays at its prior level.
            this.state.drillStacks = { ...this.state.drillStacks, [meta.id]: stack };
        } finally {
            this.state.loadingIds[meta.id] = false;
        }
    }

    async drillUp(meta, level) {
        // Climb back to a breadcrumb level (0 = the widget's own top view).
        const stack = (this.state.drillStacks[meta.id] || []).slice(0, level);
        this.state.drillStacks = { ...this.state.drillStacks, [meta.id]: stack };
        this.state.loadingIds[meta.id] = true;
        try {
            let p;
            if (stack.length) {
                p = await this.orm.call("eh.board.dashboard", "get_item_drilled",
                    [[this.state.dashboardId], meta.id, stack, this.options]);
            } else {
                const arr = await this.orm.call("eh.board.dashboard", "get_item_data",
                    [[this.state.dashboardId], [meta.id], this.options]);
                p = arr && arr[0];
            }
            if (p) this.state.payloads[meta.id] = p;
        } finally {
            this.state.loadingIds[meta.id] = false;
        }
    }

    configureItem(meta) {
        if (meta.business_metric_id) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Detach definition to customize"),
                body: _t("This widget uses a versioned business calculation. Customizing detaches that definition. Current overdue or late cutoffs become fixed dates; review the filters after editing."),
                confirmLabel: _t("Detach and customize"),
                confirm: async () => {
                    const result = await this.orm.call("eh.board.dashboard", "detach_business_metric",
                        [[this.state.dashboardId], meta.id]);
                    this._onSaved(result, true);
                    this._enterEdit();
                    this.state.editor = { open: true, itemId: meta.id };
                },
            });
            return;
        }
        // Open the full-screen editor pre-filled - NOT a modal, NOT the raw form.
        this._enterEdit();
        this.state.editor = { open: true, itemId: meta.id };
    }

    // -- export -------------------------------------------------------------
    toggleExport() {
        this.state.exportOpen = !this.state.exportOpen;
    }
    get analysisOptions() {
        const paths = {};
        for (const meta of this.state.metas) {
            const path = (this.state.drillStacks || {})[meta.id];
            if (path?.length) paths[String(meta.id)] = path;
        }
        return JSON.parse(JSON.stringify({ ...this.options, drill_paths: paths }));
    }
    _exportUrl(format) {
        const opts = encodeURIComponent(JSON.stringify(this.analysisOptions));
        return `/eh_board/export/${format}?dashboard_id=${this.state.dashboardId}&options=${opts}`;
    }
    exportCsv() {
        this.state.exportOpen = false;
        if (this.state.dashboardId) window.location = this._exportUrl("csv");
    }
    exportXlsx() {
        // Server-side workbook - a sheet per widget, numbers matched to the board.
        this.state.exportOpen = false;
        if (!this.state.dashboardId) return;
        window.location = this._exportUrl("xlsx");
    }
    exportPdfDoc() {
        // Server QWeb PDF document - login-less, shareable, no browser dialog.
        this.state.exportOpen = false;
        if (!this.state.dashboardId) return;
        window.location = this._exportUrl("pdf");
    }
    async printPdf() {
        // Real charts in the PDF: force a clean light, view-only layout and hand
        // the print stylesheet to the browser's own Save-as-PDF. No server render,
        // no rasterising - the vectors stay crisp.
        this.state.exportOpen = false;
        const id = this.state.dashboardId;
        const options = this.analysisOptions;
        try {
            const data = await this.orm.call("eh.board.dashboard", "get_export_data", [[id], options]);
            if (id !== this.state.dashboardId || JSON.stringify(options) !== JSON.stringify(this.analysisOptions)) {
                this.notification.add(_t("Filters changed. Export again to use the current view."), { type: "warning" });
                return;
            }
            for (const payload of data.items) {
                this.state.payloads[payload.id] = payload;
                delete this.state.lazyIds[payload.id];
                this.state.loadingIds[payload.id] = false;
            }
        } catch (error) {
            this.notification.add(_t("Could not prepare the complete dashboard for export."), { type: "danger" });
            return;
        }
        this._printPrev = { mode: this.state.mode, theme: this.state.theme };
        this.state.mode = "view";
        this.state.theme = "light";
        this._applyTheme();
        const restore = () => {
            if (!this._printPrev) return;
            this.state.mode = this._printPrev.mode;
            this.state.theme = this._printPrev.theme;
            this._applyTheme();
            this._printPrev = null;
            browser().removeEventListener("afterprint", restore);
        };
        browser().addEventListener("afterprint", restore);
        browser().setTimeout(() => browser().print(), 120);
    }
    async exportJson() {
        // Portable configuration only: no live rows, credentials, or SQL text.
        this.state.exportOpen = false;
        const out = await this.orm.call(
            "eh.board.dashboard", "export_definition", [[this.state.dashboardId]]);
        out.exported_at = new Date().toISOString();
        downloadText(`${this.state.name || "dashboard"}.json`,
            JSON.stringify(out, null, 2), "application/json");
    }
    triggerImport() {
        // Bound from both the main drawer and the export menu; close both, or
        // the one it was not opened from stays up over the file picker.
        this.state.menuOpen = false;
        this.state.exportOpen = false;
        if (this.state.canEdit && this.importRef.el) this.importRef.el.click();
    }
    async onImportFile(ev) {
        const file = ev.target.files && ev.target.files[0];
        ev.target.value = "";
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {
            this.notification.add(_t("Dashboard backup is larger than 2 MB."), { type: "danger" });
            return;
        }
        try {
            const definition = JSON.parse(await file.text());
            const result = await this.orm.call(
                "eh.board.dashboard", "import_definition", [definition]);
            this.state.dashboardId = result.dashboard_id;
            this.state.drillStacks = {};
            this.state.crossFilters = [];
            this.state.filterValues = {};
            await this.loadData();
            this.notification.add(_t("Dashboard imported as a private draft."), { type: "success" });
        } catch (error) {
            this.notification.add(error.message || _t("Invalid dashboard backup."), { type: "danger" });
        }
    }

    // -- auto refresh -------------------------------------------------------
    _scheduleRefresh() {
        this._clearTimer();
        // "interval" polls every N seconds. "live" has no bus push yet, so it
        // falls back to a brisk 15s poll rather than silently never refreshing.
        const mode = this.state.refreshMode;
        let secs = parseInt(this.state.refreshInterval, 10) || 0;
        if (mode === "live") {
            secs = Math.min(secs || 15, 15) || 15;
        }
        if ((mode === "interval" || mode === "live") && secs > 0) {
            this._refreshTimer = browser().setInterval(
                () => this.refreshItems(), secs * 1000);
        }
    }
    _clearTimer() {
        if (this._refreshTimer) {
            browser().clearInterval(this._refreshTimer);
            this._refreshTimer = null;
        }
    }
}

function periodRange(iso, granularity) {
    if (!iso || typeof iso !== "string") return null;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const e = new Date(d);
    switch (granularity) {
        case "day": e.setDate(e.getDate() + 1); break;
        case "week": e.setDate(e.getDate() + 7); break;
        case "quarter": e.setMonth(e.getMonth() + 3); break;
        case "year": e.setFullYear(e.getFullYear() + 1); break;
        case "month":
        default: e.setMonth(e.getMonth() + 1); break;
    }
    return { start: iso.slice(0, 10), end: e.toISOString().slice(0, 10) };
}

function browser() {
    return window;
}
function browserTheme() {
    const stored = window.localStorage.getItem(THEME_KEY);
    if (stored) return stored;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark" : "light";
}
function downloadText(name, text, mime) {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
}

registry.category("actions").add("eh_board.board", BoardAction);
