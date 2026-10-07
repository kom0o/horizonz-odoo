/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class RemoteSourceDialog extends Component {
    static template = "eh_board.RemoteSourceDialog";
    static components = { Dialog };
    static props = {
        dashboardId: Number,
        sourceId: { type: Number, optional: true },
        provider: { type: String, optional: true },
        onSaved: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.sourceId = this.props.sourceId || false;
        this.state = useState({
            provider: this.props.provider || "rest", name: "", remote_url: "", remote_path: "",
            sheets_id: "", sheets_range: "Sheet1!A1:F1001", remote_auth: this.props.provider === "sheets" ? "service_account" : "none",
            remote_header_name: "X-API-Key", remote_token_expires: "", remote_pagination: "none",
            remote_page_param: "page", remote_size_param: "limit", remote_page_size: 500,
            remote_max_pages: 5, remote_refresh_minutes: 60, remote_enabled: true,
            remote_audience_ack: false, secret: "", username: "", has_secret: false,
            credential_id: false, status: null, saving: false, error: "",
        });
        onWillStart(async () => {
            if (!this.sourceId) return;
            const config = await this.orm.call("eh.board.datasource", "remote_config", [this.props.dashboardId, this.sourceId]);
            Object.assign(this.state, config);
            this.state.remote_token_expires = (config.remote_token_expires || "").replace(" ", "T").slice(0, 16);
        });
    }

    get title() {
        return this.sourceId ? _t("Edit remote data source") : _t("Connect Google Sheets or REST data");
    }

    setProvider(event) {
        if (this.sourceId) return;
        this.state.provider = event.target.value;
        this.state.remote_auth = this.state.provider === "sheets" ? "service_account" : "none";
    }

    get canSave() {
        const s = this.state;
        return !!(s.name.trim() && s.remote_audience_ack
            && (s.provider === "sheets" ? s.sheets_id.trim() && s.sheets_range.trim() : s.remote_url.trim())
            && (s.remote_auth === "none" || s.secret.trim() || s.has_secret)
            && (s.remote_auth !== "bearer" || s.remote_token_expires));
    }

    async onKeyFile(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        if (file.size > 20000) {
            this.state.error = _t("The service-account JSON must be smaller than 20 KB.");
            return;
        }
        try {
            const text = await file.text();
            const parsed = JSON.parse(text);
            if (parsed.type !== "service_account" || !parsed.client_email || !parsed.private_key) throw new Error();
            this.state.secret = text;
            this.state.error = "";
        } catch {
            this.state.error = _t("Choose a valid Google service-account JSON key.");
        }
        event.target.value = "";
    }

    async save() {
        if (!this.canSave || this.state.saving) return;
        this.state.saving = true;
        this.state.error = "";
        try {
            const s = this.state;
            const values = {};
            for (const key of ["provider", "name", "remote_url", "remote_path", "sheets_id", "sheets_range", "remote_auth",
                "remote_header_name", "remote_pagination", "remote_page_param", "remote_size_param", "remote_page_size",
                "remote_max_pages", "remote_refresh_minutes", "remote_enabled", "remote_audience_ack", "credential_id",
                "secret", "username"]) values[key] = s[key];
            values.remote_token_expires = s.remote_token_expires ? s.remote_token_expires.replace("T", " ") + ":00" : false;
            const saved = await this.orm.call("eh.board.datasource", "remote_save_config", [this.props.dashboardId, values, this.sourceId]);
            this.sourceId = saved.id;
            // Explicit user refresh only; ordinary widget views never contact upstream servers.
            await this.orm.call("eh.board.datasource", "action_refresh_remote", [[saved.id]]);
            const config = await this.orm.call("eh.board.datasource", "remote_config", [this.props.dashboardId, saved.id]);
            this.state.status = config.status;
            this.state.secret = "";
            this.state.has_secret = config.has_secret;
            this.state.credential_id = config.credential_id;
            if (config.status.error) {
                this.state.error = config.status.error;
                return;
            }
            this.props.onSaved(config.source);
            this.notification.add(_t("Remote snapshot saved. Scheduled refresh is ready."), { type: "success" });
            this.props.close();
        } catch (error) {
            this.state.error = error.data?.message || error.message || _t("Could not save the remote source.");
        } finally {
            this.state.saving = false;
        }
    }
}
