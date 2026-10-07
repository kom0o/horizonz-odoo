/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Template gallery: pick a ready-made vertical dashboard (or a saved one) and
 * spin up a live board from it. Packs whose base app is not installed show as
 * unavailable rather than failing. */

import { _t } from "@web/core/l10n/translation";
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { BoardItem } from "./board_item";

const CATEGORY_LABELS = {
    get general() { return _t("General"); }, get account() { return _t("Accounting"); }, get crm() { return _t("Sales & CRM"); },
    get pos() { return _t("Point of Sale"); }, get stock() { return _t("Inventory"); }, get hr() { return _t("Human Resources"); }, get web() { return _t("Website"); },
};

export class TemplateGallery extends Component {
    static template = "eh_board.BusinessGallery";
    static components = { Dialog, BoardItem };
    static props = {
        dashboardId: { type: [Number, { value: null }], optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ templates: [], packs: [], loading: true, selected: null,
            preview: null, previewing: false, creating: false, error: "" });
        this.previewToken = 0;
        this._ids = this.props.dashboardId ? [this.props.dashboardId] : [];
        onWillStart(async () => {
            try {
                const [templates, packs] = await Promise.all([
                    this.orm.call("eh.board.dashboard", "get_templates", [this._ids]),
                    this.orm.call("eh.board.dashboard", "get_business_packs", []),
                ]);
                this.state.templates = templates.filter((t) => !t.business_pack_key);
                this.state.packs = packs;
            } catch (error) {
                this.state.error = error.message || _t("Could not load dashboard packs.");
            } finally {
                this.state.loading = false;
            }
        });
    }

    noop() {}

    async selectPack(pack, event) {
        if (!pack.available || this.state.creating) return;
        const gallery = event?.currentTarget?.closest(".eh_business_gallery");
        const token = ++this.previewToken;
        this.state.selected = pack;
        this.state.preview = null;
        this.state.previewing = true;
        this.state.error = "";
        try {
            const result = await this.orm.call("eh.board.dashboard", "preview_business_pack", [pack.id]);
            if (token === this.previewToken) {
                this.state.preview = result;
                await new Promise((resolve) => requestAnimationFrame(resolve));
                await new Promise((resolve) => requestAnimationFrame(resolve));
                if (token === this.previewToken && gallery?.isConnected) {
                    gallery.querySelector(".eh_business_preview")?.scrollIntoView({ block: "start" });
                }
            }
        } catch (error) {
            if (token === this.previewToken) this.state.error = error.message || _t("Could not preview this pack.");
        } finally {
            if (token === this.previewToken) this.state.previewing = false;
        }
    }

    async createPack() {
        if (!this.state.selected || !this.state.preview || this.state.creating) return;
        this.state.creating = true;
        this.state.error = "";
        try {
            const action = await this.orm.call("eh.board.dashboard", "create_business_pack", [this.state.selected.id]);
            this.props.close();
            await this.action.doAction(action);
        } catch (error) {
            this.state.error = error.message || _t("Could not create this dashboard.");
            this.state.creating = false;
        }
    }

    categoryLabel(key) {
        return CATEGORY_LABELS[key] || key;
    }

    async use(t) {
        if (!t.available || this.state.creating) return;
        this.state.creating = true;
        try {
            const action = await this.orm.call(
                "eh.board.dashboard", "apply_template", [this._ids, t.id]);
            if (action && action.tag) {
                this.props.close();
                await this.action.doAction(action);
            } else if (action && action.error) {
                this.notification.add(action.error, { type: "warning" });
            }
        } catch (error) {
            this.notification.add(error.message || _t("Could not create this dashboard."), { type: "danger" });
        } finally {
            this.state.creating = false;
        }
    }
}
