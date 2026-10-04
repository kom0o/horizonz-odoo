from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError

class HrLoan(models.Model):
    _name = 'hr.loan'
    _description = 'HR Loan'

    name = fields.Char(string="Loan Name", default="/", readonly=True)
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True)
    type = fields.Selection([
        ('loan', 'Loan'),
        ('debt', 'Debt')
    ], string="Type", required=True)
    
    loan_type = fields.Selection([
        ('hiring_loan', 'Hiring Loan'),
        ('personal_loan', 'Personal Loan')
    ], string="Loan Type")
    
    debt_type = fields.Selection([
        ('traffic_fees', 'Traffic Fees'),
        ('travel_ticket', 'Travel Ticket'),
        ('travel_visa', 'Travel Visa'),
        ('others', 'Others'),
        ('accedent_fees', 'Accedent Fees'),
        ('car_insurance_fees', 'Car Insurance Fees'),
        ('driving_license_fees', 'Driving License Fees'),
        ('custody_gap_fees', 'Custody Gap Fees'),
        ('penalty_fees', 'Penalty Fees')
    ], string="Debt Type")
    
    amount = fields.Float(string="Amount", required=True)
    
    installment_by = fields.Selection([
        ('amount', 'Amount'),
        ('number', 'Number')
    ], string="Installment By", required=True)
    
    installment_amount = fields.Float(string="Installment Amount")
    no_of_installments = fields.Integer(string="No. of Installments")
    
    request_date = fields.Date(string="Request Date", default=fields.Date.context_today)
    payment_start_date = fields.Date(string="Payment Start Date", required=True)
    
    debit_account_id = fields.Many2one('account.account', string="Debit Account")
    credit_account_id = fields.Many2one('account.account', string="Credit Account")
    journal_id = fields.Many2one('account.journal', string="Journal")
    journal_entry_id = fields.Many2one('account.move', string="Journal Entry Id", readonly=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed')
    ], string="State", default="draft", tracking=True)
    
    line_ids = fields.One2many('hr.loan.line', 'loan_id', string="Details")

    @api.onchange('amount', 'installment_by', 'installment_amount', 'no_of_installments')
    def _onchange_installments(self):
        for rec in self:
            if rec.amount > 0:
                if rec.installment_by == 'amount' and rec.installment_amount > 0:
                    rec.no_of_installments = int(rec.amount / rec.installment_amount)
                elif rec.installment_by == 'number' and rec.no_of_installments > 0:
                    rec.installment_amount = rec.amount / rec.no_of_installments
                    
    def action_compute_installments(self):
        for rec in self:
            rec.line_ids.unlink()
            if not rec.payment_start_date:
                raise UserError("Please select a Payment Start Date")
            if not rec.amount or rec.amount <= 0:
                raise UserError("Amount must be greater than 0")
                
            if rec.installment_by == 'amount':
                if not rec.installment_amount or rec.installment_amount <= 0:
                    raise UserError("Installment Amount must be greater than 0")
                no_installments = int(rec.amount / rec.installment_amount)
                amount = rec.installment_amount
            else:
                if not rec.no_of_installments or rec.no_of_installments <= 0:
                    raise UserError("No. of Installments must be greater than 0")
                no_installments = rec.no_of_installments
                amount = rec.amount / rec.no_of_installments
                
            date_start = rec.payment_start_date
            lines = []
            for i in range(1, no_installments + 1):
                lines.append((0, 0, {
                    'installment_date': date_start,
                    'amount': amount,
                }))
                date_start = date_start + relativedelta(months=1)
            rec.line_ids = lines

    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'

class HrLoanLine(models.Model):
    _name = 'hr.loan.line'
    _description = 'HR Loan Line'

    loan_id = fields.Many2one('hr.loan', string="Loan", ondelete="cascade")
    installment_date = fields.Date(string="Installment Date")
    amount = fields.Float(string="Amount")
    paid = fields.Boolean(string="Paid")
