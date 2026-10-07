/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * A small original rich-text field for content widgets: a contenteditable
 * surface with a formatting toolbar. No web_editor mount, no third-party
 * editor bundle - it keeps the module's zero-heavy-dependency footprint while
 * giving a real WYSIWYG instead of a raw HTML textarea. */

import { _t } from "@web/core/l10n/translation";

import { Component, useRef, onMounted } from "@odoo/owl";

export class RichEditor extends Component {
    static template = "eh_board.RichEditor";
    static props = {
        value: { type: String, optional: true },
        onChange: Function,
    };

    setup() {
        this.ref = useRef("editable");
        onMounted(() => {
            if (this.ref.el) this.ref.el.innerHTML = this.props.value || "";
        });
    }

    cmd(command, arg) {
        this.ref.el.focus();
        document.execCommand(command, false, arg);
        this.sync();
    }
    link() {
        const url = window.prompt(_t("Link URL (https://...)"));
        if (url) this.cmd("createLink", url);
    }
    sync() {
        this.props.onChange(this.ref.el.innerHTML);
    }
}
