from odoo import models, fields, api

class HrTravelTicket(models.Model):
    _name = 'hr.travel.ticket'
    _description = 'Travel Ticket Request'
    _rec_name = 'employee_id'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
        ('cancel', 'Cancel'),
    ], string='Status', default='draft', track_visibility='onchange')

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    last_back_date = fields.Date(string='Last Back Date')
    worked_days = fields.Float(string='Worked Days', default=0.0)
    days_for_ticket = fields.Float(string='# Days for Ticket', default=660.0)
    
    # Contract related - changing to Char since hr.contract module is missing
    contract_id = fields.Char(string='Contract')
    
    country_id = fields.Many2one('res.country', string='Country')
    airport = fields.Char(string='Airport')
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    request_date = fields.Date(string='Request Date', default=fields.Date.context_today)
    travel_date = fields.Date(string='Travel Date')
    
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('check', 'Check'),
    ], string='Payment Method')
    
    actual_ticket_amount = fields.Float(string='Actual Ticket Amount', default=0.0)
    actual_visa_amount = fields.Float(string='Actual Visa Amount', default=0.0)
    
    additional_cost_by_employee = fields.Boolean(string='Additional Cost By Employee')
    is_settlement = fields.Boolean(string='Is Settlement')

    ticket_line_ids = fields.One2many('hr.travel.ticket.line', 'ticket_id', string='Available Tickets')

    def action_confirm(self):
        for record in self:
            if record.state == 'draft':
                record.state = 'confirmed'


class HrTravelTicketLine(models.Model):
    _name = 'hr.travel.ticket.line'
    _description = 'Travel Ticket Line'

    ticket_id = fields.Many2one('hr.travel.ticket', string='Ticket Reference', required=True, ondelete='cascade')
    name = fields.Char(string='Ticket')
    dependent = fields.Char(string='Dependent')
    relationship = fields.Selection([
        ('spouse', 'Spouse'),
        ('child', 'Child'),
        ('other', 'Other'),
    ], string='Relationship')
    type = fields.Selection([
        ('one_way', 'One Way'),
        ('round_trip', 'Round Trip'),
    ], string='Type')
    ticket_value = fields.Float(string='Ticket Value', default=0.0)
