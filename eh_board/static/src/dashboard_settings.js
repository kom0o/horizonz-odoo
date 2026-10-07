/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Dashboard-level settings panel: name, visibility/sharing, palette, density,
 * default date range, auto-refresh and email digest. Owner / builder only.
 * A plain Dialog over the board so settings are always one click away. */

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const UNIT_SECONDS = { seconds: 1, minutes: 60, hours: 3600 };
const PALETTES = [
    {
        key: "default", get label() { return _t("Heritage"); },
        light: ["#2563a9", "#087f5b", "#986400", "#6842a8", "#c23b4a"],
        dark: ["#69a9f5", "#49cfa0", "#ffc857", "#b39af2", "#ff8790"],
    },
    {
        key: "ocean", get label() { return _t("Ocean"); },
        light: ["#006daa", "#007a78", "#365a7c", "#654a86", "#a84c38"],
        dark: ["#62b5e5", "#45c8c5", "#8eaad0", "#b29ad6", "#f08c76"],
    },
    {
        key: "sunset", get label() { return _t("Sunset"); },
        light: ["#b94a3b", "#a45a00", "#bf1645", "#7134a7", "#a83f70"],
        dark: ["#ff8d7d", "#ffb05e", "#ff7095", "#be91f2", "#f48abb"],
    },
    {
        key: "forest", get label() { return _t("Forest"); },
        light: ["#256348", "#287653", "#5f5584", "#916020", "#356c75"],
        dark: ["#75c7a0", "#57d09a", "#b2a1dc", "#e0ae68", "#6cc4ce"],
    },
    {
        key: "mono", get label() { return _t("Monochrome"); },
        light: ["#1b2733", "#526777", "#31475a", "#718593", "#405669"],
        dark: ["#e2e8ec", "#91a3b0", "#c5d0d7", "#7e94a3", "#d3dce2"],
    },
];

export class DashboardSettings extends Component {
    static template = "eh_board.DashboardSettings";
    static components = { Dialog };
    static props = {
        dashboardId: Number,
        onSaved: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.palettes = PALETTES;
        this.state = useState({
            loading: true, saving: false, s: {}, users: [], canEdit: false,
            refreshValue: 1, refreshUnit: "minutes",
            search: { shared_user_ids: "", digest_user_ids: "" },
        });
        onWillStart(async () => {
            const s = await this.orm.call(
                "eh.board.dashboard", "get_settings", [[this.props.dashboardId]]);
            this.state.s = s;
            this.state.users = s.users || [];
            this.state.canEdit = !!s.can_edit;
            this._splitInterval(s.refresh_interval || 60);
            this.state.loading = false;
        });
    }

    // -- auto-refresh value + unit <-> seconds -------------------------------
    _splitInterval(secs) {
        // Show the friendliest unit: whole hours, else whole minutes, else seconds.
        if (secs % 3600 === 0) { this.state.refreshValue = secs / 3600; this.state.refreshUnit = "hours"; }
        else if (secs % 60 === 0) { this.state.refreshValue = secs / 60; this.state.refreshUnit = "minutes"; }
        else { this.state.refreshValue = secs; this.state.refreshUnit = "seconds"; }
    }
    get intervalSeconds() {
        const v = Math.max(1, parseInt(this.state.refreshValue, 10) || 1);
        return v * (UNIT_SECONDS[this.state.refreshUnit] || 1);
    }

    // -- people picker (search + click to add, chip to remove) --------------
    userName(id) {
        const u = this.state.users.find((x) => x.id === id);
        return u ? u.name : "#" + id;
    }
    selectedUsers(key) {
        return (this.state.s[key] || []).map((id) => ({ id, name: this.userName(id) }));
    }
    filteredUsers(key) {
        const q = (this.state.search[key] || "").toLowerCase().trim();
        const chosen = new Set(this.state.s[key] || []);
        return this.state.users.filter((u) =>
            !chosen.has(u.id) && (!q || u.name.toLowerCase().includes(q)));
    }
    toggleUser(key, id) {
        if (!this.state.canEdit) return;
        const cur = this.state.s[key] || [];
        this.state.s[key] = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    }
    selectPalette(key) {
        if (this.state.canEdit) this.state.s.palette = key;
    }

    async save() {
        if (!this.state.canEdit) return;
        this.state.saving = true;
        const s = this.state.s;
        const vals = {
            name: s.name,
            description: s.description || "",
            parent_dashboard_id: parseInt(s.parent_dashboard_id, 10) || false,
            published: !!s.published,
            palette: s.palette,
            density: s.density,
            default_date_preset: s.default_date_preset,
            refresh_mode: s.refresh_mode,
            refresh_interval: this.intervalSeconds,
            digest_enabled: !!s.digest_enabled,
            digest_frequency: s.digest_frequency || "weekly",
            digest_weekday: s.digest_weekday || "0",
            digest_month_day: s.digest_month_day || 1,
            digest_hour: s.digest_hour ?? 8,
            shared_user_ids: s.shared_user_ids || [],
            digest_user_ids: s.digest_user_ids || [],
        };
        try {
            const saved = await this.orm.call(
                "eh.board.dashboard", "save_settings", [[this.props.dashboardId], vals]);
            this.props.onSaved(saved);
            this.props.close();
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
        this.state.saving = false;
    }
}
