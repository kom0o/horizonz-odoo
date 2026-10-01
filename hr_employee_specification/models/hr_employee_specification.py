from odoo import models, fields, api
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeSpecificationSetup(models.Model):
    _name = 'hr.employee.specification.setup'
    _description = 'Global Specification Configuration'
    _rec_name = 'spec_type'

    spec_type = fields.Selection([
        ('medical', 'Medical'),
        ('iqama', 'Iqama'),
        ('end_of_service', 'End of Service'),
        ('allocation', 'Allocation'),
        ('travel_ticket', 'Travel Ticket'),
        ('visa', 'Visa'),
    ], string='Specification Type', required=True, unique=True)

    issue_day = fields.Integer(string='Issue Day of Month', required=True, default=1, help='Day of the month to generate the specification (1-28)')
    journal_id = fields.Many2one('account.journal', string='Journal', required=True)
    debit_account_id = fields.Many2one('account.account', string='Debit Account', required=True)
    credit_account_id = fields.Many2one('account.account', string='Credit Account', required=True)

    _sql_constraints = [
        ('unique_spec_type', 'unique(spec_type)', 'A global configuration for this specification type already exists!')
    ]


class HrEmployeeSpecificationConfig(models.Model):
    _name = 'hr.employee.specification.config'
    _description = 'Employee Specification Configuration'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    
    spec_type = fields.Selection([
        ('medical', 'Medical'),
        ('iqama', 'Iqama'),
        ('end_of_service', 'End of Service'),
        ('allocation', 'Allocation'),
        ('travel_ticket', 'Travel Ticket'),
        ('visa', 'Visa'),
    ], string='Type', required=True)
    
    total_amount = fields.Float(string='Total Amount', required=True, default=0.0)
    
    divide_by = fields.Selection([
        ('11', '11 Months'),
        ('12', '12 Months'),
    ], string='Divide By', required=True, default='12')
    
    monthly_amount = fields.Float(string='Monthly Amount', compute='_compute_monthly_amount', store=True)

    @api.onchange('spec_type')
    def _onchange_spec_type(self):
        if self.spec_type in ['travel_ticket', 'visa']:
            self.divide_by = '11'
        else:
            self.divide_by = '12'

    @api.depends('total_amount', 'divide_by')
    def _compute_monthly_amount(self):
        for record in self:
            if record.divide_by and record.total_amount:
                divisor = int(record.divide_by)
                record.monthly_amount = record.total_amount / divisor if divisor > 0 else 0.0
            else:
                record.monthly_amount = 0.0


class HrEmployeeSpecification(models.Model):
    _name = 'hr.employee.specification'
    _description = 'Employee Monthly Specification'
    
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    config_id = fields.Many2one('hr.employee.specification.config', string='Configuration', ondelete='set null')
    spec_type = fields.Selection(related='config_id.spec_type', string='Type', store=True)
    date = fields.Date(string='Date generated', default=fields.Date.context_today)
    amount = fields.Float(string='Amount', required=True)
    
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)

    @api.model
    def _generate_monthly_specifications(self):
        """ Cron job to generate monthly specifications based on configuration """
        today = date.today()
        current_day = today.day
        
        # Find active employees that have specifications enabled
        employees = self.env['hr.employee'].search([('has_specifications', '=', True)])
        if not employees:
            return
            
        # Get all global setups that should run today
        setups = self.env['hr.employee.specification.setup'].search([('issue_day', '=', current_day)])
        if not setups:
            return

        spec_types_today = setups.mapped('spec_type')
        setup_dict = {setup.spec_type: setup for setup in setups}
            
        configs = self.env['hr.employee.specification.config'].search([
            ('employee_id', 'in', employees.ids),
            ('spec_type', 'in', spec_types_today)
        ])
        
        _logger.info(f"Running monthly specification cron job. Found {len(configs)} configs for {len(spec_types_today)} types on day {current_day}.")
        
        for config in configs:
            if config.monthly_amount <= 0:
                continue
                
            # Check if one was already generated this month to prevent duplicates
            start_date = today.replace(day=1)
            existing = self.search([
                ('config_id', '=', config.id),
                ('date', '>=', start_date)
            ], limit=1)
            
            if existing:
                continue
                
            setup = setup_dict.get(config.spec_type)
            if not setup:
                continue

            # Generate Journal Entry
            move_vals = {
                'journal_id': setup.journal_id.id,
                'date': today,
                'ref': f"{config.employee_id.name} - {dict(config._fields['spec_type'].selection).get(config.spec_type)} Accrual",
                'line_ids': [
                    (0, 0, {
                        'name': f"{dict(config._fields['spec_type'].selection).get(config.spec_type)} Accrual - {config.employee_id.name}",
                        'account_id': setup.debit_account_id.id,
                        'debit': config.monthly_amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': f"{dict(config._fields['spec_type'].selection).get(config.spec_type)} Accrual - {config.employee_id.name}",
                        'account_id': setup.credit_account_id.id,
                        'debit': 0.0,
                        'credit': config.monthly_amount,
                    })
                ]
            }
            
            try:
                move = self.env['account.move'].create(move_vals)
                # Keep as draft for review
                
                # Create the specification record
                self.create({
                    'employee_id': config.employee_id.id,
                    'config_id': config.id,
                    'date': today,
                    'amount': config.monthly_amount,
                    'move_id': move.id,
                })
            except Exception as e:
                _logger.error(f"Failed to create specification for {config.employee_id.name}: {e}")
