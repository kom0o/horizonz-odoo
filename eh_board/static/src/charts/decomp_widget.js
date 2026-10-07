/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * Decomposition tree: a measure total broken down level by level along the
 * dimension chain. Click a node to expand it by the next dimension; the tree
 * fetches each level on demand (self-contained via the orm service). Original
 * OWL/HTML - no external tree lib. */

import { uiText } from "../ui_text";

import { _t } from "@web/core/l10n/translation";

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { formatValue } from "./svg_util";

export class DecompWidget extends Component {
    static template = "eh_board.DecompWidget";
    uiText = uiText;
    static props = {
        payload: Object,
        meta: { type: Object, optional: true },
        onDrill: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        const p = this.props.payload;
        const l0 = p.level0 || {};
        this.state = useState({
            cols: [{ field: l0.field, nodes: l0.nodes || [], sel: -1, leaf: !!l0.leaf }],
            busy: false,
        });
    }

    get root() { return this.props.payload.root || { label: _t("Total"), value: 0 }; }
    get chainLabels() { return this.props.payload.chain_labels || []; }
    fmt(v) {
        const p = this.props.payload;
        return formatValue(v, p.number_format || "compact", p.currency, p.unit || "");
    }

    colMax(col) {
        return Math.max(1, ...(col.nodes || []).map((n) => Math.abs(n.value)));
    }
    barW(node, col) {
        return Math.round((Math.abs(node.value) / this.colMax(col)) * 100);
    }

    async expand(ci, ni) {
        if (this.state.busy) return;
        const col = this.state.cols[ci];
        if (col.leaf) { col.sel = ni; return; }
        col.sel = ni;
        this.state.cols = this.state.cols.slice(0, ci + 1);   // drop deeper columns
        const path = [];
        for (let i = 0; i <= ci; i++) {
            const c = this.state.cols[i];
            const n = c.nodes[c.sel];
            if (n) path.push({ field: c.field, value: n.key });
        }
        const dashId = this.props.meta && this.props.meta.dashboard_id;
        const itemId = this.props.meta && this.props.meta.id;
        if (!dashId || !itemId) return;
        this.state.busy = true;
        try {
            const res = await this.orm.call(
                "eh.board.dashboard", "get_item_decomp", [[dashId], itemId, path]);
            if (res && (res.nodes || []).length) {
                this.state.cols.push({ field: res.field, nodes: res.nodes, sel: -1, leaf: !!res.leaf });
            }
        } finally {
            this.state.busy = false;
        }
    }
}
