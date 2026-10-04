from odoo import models, fields, api

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_payslip_done(self):
        res = super(HrPayslip, self).action_payslip_done()
        for payslip in self:
            loan_lines = self.env['hr.loan.line'].search([
                ('loan_id.employee_id', '=', payslip.employee_id.id),
                ('loan_id.state', '=', 'confirmed'),
                ('paid', '=', False),
                ('installment_date', '>=', payslip.date_from),
                ('installment_date', '<=', payslip.date_to)
            ])
            if loan_lines:
                loan_lines.write({
                    'paid': True,
                    'payslip_id': payslip.id
                })
        return res

    def action_payslip_draft(self):
        res = super(HrPayslip, self).action_payslip_draft()
        for payslip in self:
            loan_lines = self.env['hr.loan.line'].search([
                ('payslip_id', '=', payslip.id)
            ])
            if loan_lines:
                loan_lines.write({
                    'paid': False,
                    'payslip_id': False
                })
        return res

    def get_loan_amount(self):
        self.ensure_one()
        loan_lines = self.env['hr.loan.line'].search([
            ('loan_id.employee_id', '=', self.employee_id.id),
            ('loan_id.state', '=', 'confirmed'),
            ('paid', '=', False),
            ('installment_date', '>=', self.date_from),
            ('installment_date', '<=', self.date_to)
        ])
        return sum(loan_lines.mapped('amount'))
