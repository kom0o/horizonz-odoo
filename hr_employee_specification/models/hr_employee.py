from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    has_specifications = fields.Boolean(string="Has Specifications", default=False)
    specification_config_ids = fields.One2many('hr.employee.specification.config', 'employee_id', string='Specifications Config')
