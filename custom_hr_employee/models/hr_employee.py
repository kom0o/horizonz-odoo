# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from werkzeug.security import generate_password_hash

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    arabic_name = fields.Char(string='Arabic Name', tracking=True)
    employee_code = fields.Char(string='Employee Code', copy=False, tracking=True, index=True)

    portal_username = fields.Char(string='Username', groups="base.group_user")
    portal_password = fields.Char(string='Password', copy=False, groups="base.group_user")

    _rec_names_search = ['name', 'arabic_name', 'employee_code']

    @api.constrains('employee_code', 'company_id')
    def _check_employee_code_unique(self):
        for rec in self:
            if rec.employee_code:
                domain = [
                    ('employee_code', '=', rec.employee_code),
                    ('id', '!=', rec.id),
                ]
                if rec.company_id:
                    domain.append(('company_id', '=', rec.company_id.id))
                if self.search_count(domain) > 0:
                    raise ValidationError(_("The Employee Code '%s' is already assigned to another employee.", rec.employee_code))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('portal_password'):
                vals['portal_password'] = generate_password_hash(vals['portal_password'])
        return super(HrEmployee, self).create(vals_list)

    def write(self, vals):
        if vals.get('portal_password'):
            vals['portal_password'] = generate_password_hash(vals['portal_password'])
        return super(HrEmployee, self).write(vals)


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    arabic_name = fields.Char(string='Arabic Name', readonly=True)
    employee_code = fields.Char(string='Employee Code', readonly=True)
