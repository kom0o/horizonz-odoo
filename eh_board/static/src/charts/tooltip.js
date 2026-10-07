/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * A single shared cursor tooltip for every chart. One DOM node, moved and
 * filled on hover - the interaction the incumbents charge for and we ship on
 * every widget. Pure DOM, no OWL, so any chart can call it. */

let _el = null;

function ensure() {
    if (_el) return _el;
    _el = document.createElement("div");
    _el.className = "eh_board_tooltip";
    _el.style.display = "none";
    document.body.appendChild(_el);
    return _el;
}

/** Show the tooltip near the pointer. `rows` is [{label, value, color}]. */
export function showTooltip(ev, title, rows) {
    const el = ensure();
    const body = (rows || [])
        .map((r) => `<div class="eh_board_tt_row">`
            + (r.color ? `<span class="eh_board_tt_dot" style="background:${r.color}"></span>` : "")
            + `<span class="eh_board_tt_label">${escapeHtml(r.label)}</span>`
            + `<span class="eh_board_tt_val">${escapeHtml(r.value)}</span></div>`)
        .join("");
    el.innerHTML = (title ? `<div class="eh_board_tt_title">${escapeHtml(title)}</div>` : "") + body;
    el.style.display = "block";
    moveTooltip(ev);
}

export function moveTooltip(ev) {
    if (!_el || _el.style.display === "none") return;
    const pad = 14;
    const w = _el.offsetWidth;
    const h = _el.offsetHeight;
    let x = ev.clientX + pad;
    let y = ev.clientY + pad;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
    _el.style.left = x + "px";
    _el.style.top = y + "px";
}

export function hideTooltip() {
    if (_el) _el.style.display = "none";
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}
