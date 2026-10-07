"""Versioned business definitions. Pure data: no queries or customer records.

Display strings use lazy translation and resolve in the caller's language.
Published IDs are immutable. A changed business definition gets a new version;
saved dashboards retain the old definition instead of changing meaning on upgrade.
"""
from copy import deepcopy

from odoo.tools.translate import _lt


METRICS = {
    "sales.confirmed_untaxed.v1": {
        "title": _lt("Confirmed untaxed sales"), "model": "sale.order", "module": "sale",
        "aggregate": "sum", "field": "amount_untaxed", "date_field": "date_order",
        "domain": [("state", "in", ["sale", "done"])], "currency": "order_company",
        "dimensions": ["user_id", "partner_id", "date_order"],
        "definition": _lt("Untaxed order value for confirmed sales orders in this company and its currency. Draft and cancelled orders are excluded. This is booked sales, not invoiced revenue. Foreign-currency orders are excluded; no conversion is performed."),
    },
    "sales.average_order.v1": {
        "title": _lt("Average confirmed order"), "model": "sale.order", "module": "sale",
        "aggregate": "avg", "field": "amount_untaxed", "date_field": "date_order",
        "domain": [("state", "in", ["sale", "done"])], "currency": "order_company",
        "dimensions": ["user_id", "partner_id", "date_order"],
        "definition": _lt("Average untaxed value per confirmed order in this company and its currency, including zero-value confirmed orders. Draft, cancelled and foreign-currency orders are excluded. Group averages must not be added together."),
    },
    "sales.confirmed_orders.v1": {
        "title": _lt("Confirmed orders"), "model": "sale.order", "module": "sale",
        "aggregate": "count", "field": None, "date_field": "date_order",
        "domain": [("state", "in", ["sale", "done"])], "currency": "order_company",
        "dimensions": ["user_id", "partner_id", "date_order"],
        "definition": _lt("Number of confirmed orders in this company and its currency. The same scope as confirmed untaxed sales; draft, cancelled and foreign-currency orders are excluded. Order date controls period filtering."),
    },
    "receivables.open_balance.v1": {
        "title": _lt("Current net customer balance"), "model": "account.move", "module": "account",
        "aggregate": "sum", "field": "amount_residual_signed", "date_field": None,
        "domain": [("state", "=", "posted"), ("move_type", "in", ["out_invoice", "out_refund"]), ("amount_residual_signed", "!=", 0)],
        "currency": "company", "dimensions": ["partner_id", "invoice_date_due"],
        "definition": _lt("Current signed residual of posted customer invoices and credit notes in company currency. Customer credit notes reduce the balance; supplier bills and drafts are excluded. This is the balance now, not a historical as-of balance. Dashboard date filters do not change this current-balance metric."),
    },
    "receivables.overdue_balance.v1": {
        "title": _lt("Current overdue net balance"), "model": "account.move", "module": "account",
        "aggregate": "sum", "field": "amount_residual_signed", "date_field": None,
        "domain": [("state", "=", "posted"), ("move_type", "in", ["out_invoice", "out_refund"]), ("amount_residual_signed", "!=", 0)],
        "dynamic": "overdue", "currency": "company", "dimensions": ["partner_id", "invoice_date_due"],
        "definition": _lt("Current signed residual of posted customer invoices and credit notes whose document due date is before today in your timezone. Due customer credit notes reduce this total. Uses document due date, not installment-level ageing. This is current exposure, not historical as-of ageing; dashboard date filters are ignored."),
    },
    "receivables.open_invoices.v1": {
        "title": _lt("Open customer invoices"), "model": "account.move", "module": "account",
        "aggregate": "count", "field": None, "date_field": None,
        "domain": [("state", "=", "posted"), ("move_type", "=", "out_invoice"), ("amount_residual_signed", "!=", 0)],
        "currency": "company", "dimensions": ["partner_id", "invoice_date_due"],
        "definition": _lt("Number of posted customer invoices with a nonzero current residual in this company. Credit notes, drafts and supplier bills are excluded. Includes partially paid invoices. Current status only; dashboard date filters are ignored."),
    },
    "receivables.open_credits.v1": {
        "title": _lt("Current customer credits"), "model": "account.move", "module": "account",
        "aggregate": "sum", "field": "amount_residual_signed", "date_field": None,
        "domain": [("state", "=", "posted"), ("move_type", "=", "out_refund"), ("amount_residual_signed", "!=", 0)],
        "currency": "company", "dimensions": ["partner_id", "invoice_date_due"],
        "definition": _lt("Signed remaining balance of posted customer credit notes in company currency, normally negative. These credits reduce net customer balances. Current status only; dashboard date filters are ignored."),
    },
    "warehouse.open_transfers.v1": {
        "title": _lt("Open transfers"), "model": "stock.picking", "module": "stock",
        "aggregate": "count", "field": None, "date_field": None,
        "domain": [("state", "not in", ["done", "cancel"])],
        "dimensions": ["picking_type_id", "state", "partner_id"],
        "definition": _lt("Current count of transfers in this company that are neither completed nor cancelled, including drafts and return transfers. Counts transfer documents, not units or stock value. Dashboard date filters are ignored for current backlog."),
    },
    "warehouse.late_transfers.v1": {
        "title": _lt("Late open transfers"), "model": "stock.picking", "module": "stock",
        "aggregate": "count", "field": None, "date_field": None,
        "domain": [("state", "not in", ["done", "cancel"])], "dynamic": "late",
        "dimensions": ["picking_type_id", "state", "partner_id"],
        "definition": _lt("Current open transfers with a scheduled date before the current instant. Completed and cancelled transfers are excluded; drafts and returns are included. Missing scheduled dates are excluded. Counts documents, not quantities. Dashboard date filters are ignored."),
    },
    "warehouse.completed_transfers.v1": {
        "title": _lt("Completed transfers"), "model": "stock.picking", "module": "stock",
        "aggregate": "count", "field": None, "date_field": "date_done",
        "domain": [("state", "=", "done")],
        "dimensions": ["picking_type_id", "date_done", "partner_id"],
        "definition": _lt("Number of completed transfers in this company, including returns and internal transfers. Completion date controls period filtering. Measures document throughput, not shipped units, net sales or inventory value."),
    },
}


PACKS = {
    "sales.v1": {
        "name": _lt("Sales performance"), "category": "crm", "module": "sale", "preset": "this_quarter",
        "description": _lt("Confirmed orders, untaxed sales and average order value, with salesperson and customer breakdowns. Company-currency orders only; foreign-currency orders are excluded."),
        "widgets": [
            ("sales.confirmed_untaxed.v1", "kpi", None),
            ("sales.average_order.v1", "kpi", None),
            ("sales.confirmed_orders.v1", "kpi", None),
            ("sales.confirmed_untaxed.v1", "hbar", "user_id"),
            ("sales.confirmed_untaxed.v1", "line", "date_order"),
            ("sales.confirmed_untaxed.v1", "list", "partner_id"),
        ],
    },
    "receivables.v1": {
        "name": _lt("Cash and receivables"), "category": "account", "module": "account", "preset": "all",
        "description": _lt("Current customer balances and overdue documents, net of credit notes, in company currency. Current residuals only: no historical as-of balances, installment ageing or cash forecast."),
        "widgets": [
            ("receivables.open_balance.v1", "kpi", None),
            ("receivables.overdue_balance.v1", "kpi", None),
            ("receivables.open_invoices.v1", "kpi", None),
            ("receivables.open_credits.v1", "kpi", None),
            ("receivables.open_balance.v1", "hbar", "partner_id"),
            ("receivables.overdue_balance.v1", "hbar", "partner_id"),
            ("receivables.open_balance.v1", "list", "invoice_date_due"),
        ],
    },
    "warehouse.v1": {
        "name": _lt("Warehouse operations"), "category": "stock", "module": "stock", "preset": "this_month",
        "description": _lt("Current open and late transfers, plus completed transfer throughput by selected completion period. Includes returns; counts documents, not units or inventory value."),
        "widgets": [
            ("warehouse.open_transfers.v1", "kpi", None),
            ("warehouse.late_transfers.v1", "kpi", None),
            ("warehouse.completed_transfers.v1", "kpi", None),
            ("warehouse.late_transfers.v1", "hbar", "picking_type_id"),
            ("warehouse.completed_transfers.v1", "line", "date_done"),
            ("warehouse.open_transfers.v1", "list", "state"),
        ],
    },
}


def metric_definition(metric_id):
    """A caller-owned copy prevents per-request customization mutating registry."""
    return deepcopy(METRICS.get(metric_id))


def metric_domain(metric_id, company_id, currency_id, today=None, now=None):
    definition = metric_definition(metric_id)
    if not definition:
        raise ValueError("Unknown business metric version.")
    domain = definition["domain"] + [("company_id", "=", company_id)]
    if definition.get("currency") == "order_company":
        domain.append(("currency_id", "=", currency_id))
    if definition.get("dynamic") == "overdue" and today:
        domain += [("invoice_date_due", "!=", False), ("invoice_date_due", "<", today)]
    if definition.get("dynamic") == "late" and now:
        domain += [("scheduled_date", "!=", False), ("scheduled_date", "<", now)]
    return domain
