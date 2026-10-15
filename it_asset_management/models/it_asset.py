from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ItAsset(models.Model):
    _name = 'it.asset'
    _description = 'IT Hardware & Digital Asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'ref desc, id desc'

    name = fields.Char(string='Asset Name / Description', required=True, tracking=True)
    ref = fields.Char(
        string='Asset Code / Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
        tracking=True
    )
    asset_type = fields.Selection([
        ('laptop', 'Laptop'),
        ('pc', 'PC / Desktop'),
        ('screen', 'Screen / Monitor'),
        ('all_in_one', 'All-In-One'),
        ('tablet', 'Tablet'),
        ('printer', 'Printer'),
        ('keyboard', 'Keyboard'),
        ('mouse', 'Mouse'),
        ('other', 'Other'),
    ], string='Asset Type', default='laptop', required=True, tracking=True)

    serial_no = fields.Char(string='Serial Number', tracking=True, index=True)
    model_sku = fields.Char(string='Model & SKU', tracking=True)

    # Hardware Specifications
    cpu = fields.Char(string='CPU / Processor')
    ram = fields.Char(string='RAM')
    nvme = fields.Char(string='NVMe Storage')
    ssd = fields.Char(string='SSD Storage')
    hdd = fields.Char(string='HDD Storage')
    keyboard_included = fields.Boolean(string='Includes Keyboard')
    mouse_included = fields.Boolean(string='Includes Mouse')

    # Software & OS Specifications
    os = fields.Char(string='Operating System')
    ms_office = fields.Char(string='MS Office')
    anti_virus = fields.Char(string='Anti-Virus')
    software_others = fields.Char(string='Other Software / Licenses')

    # Status & Confirmation State
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
    ], string='Status', default='draft', tracking=True, copy=False)

    # Condition & Stage
    condition = fields.Selection([
        ('new', 'New'),
        ('used', 'Used'),
        ('good', 'Good / Used'),
        ('fair', 'Fair'),
        ('damaged', 'Damaged / Needs Repair'),
    ], string='Physical Condition', default='new', tracking=True)

    has_been_assigned = fields.Boolean(
        string='Has Been Assigned',
        default=False,
        copy=False,
        help='Automatically tracked. Once assigned to any custodian at least once, physical condition transitions to Used.'
    )

    stage_id = fields.Many2one(
        'it.asset.stage',
        string='Stage',
        default=lambda self: self._default_stage_id(),
        group_expand='_read_group_stage_ids',
        tracking=True,
        index=True
    )
    stage_type = fields.Selection(related='stage_id.stage_type', string='Stage Type', readonly=True)

    kanban_state = fields.Selection([
        ('normal', 'In Progress'),
        ('done', 'Ready / Good'),
        ('blocked', 'Blocked / Alert')
    ], string='Kanban State', default='normal')
    color = fields.Integer(string='Color Index')
    priority = fields.Boolean(string='High Priority')
    active = fields.Boolean(string='Active', default=True)
    image_1920 = fields.Image(string='Device Photo / Avatar', max_width=1024, max_height=1024)

    # Financial & Procurement
    acquisition_date = fields.Date(string='Acquisition Date', tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    acquisition_price = fields.Monetary(
        string='Acquisition Price',
        currency_field='currency_id',
        tracking=True
    )
    warranty_status = fields.Char(string='Warranty Status')
    asset_location_id = fields.Many2one(
        'it.asset.location',
        string='Physical Location',
        tracking=True
    )

    # Current Custody / Assignment
    assigned_to_id = fields.Many2one(
        'res.partner',
        string='Assigned Employee / Custodian',
        tracking=True,
        index=True
    )
    assign_date = fields.Date(string='Current Assign Date', tracking=True)
    current_assignment_id = fields.Many2one('it.asset.assign', string='Custody Document')
    is_assigned = fields.Boolean(string='Is Assigned', compute='_compute_is_assigned', store=True)

    # Return & History
    returned = fields.Boolean(string='Marked Returned', default=False)
    return_date = fields.Date(string='Last Return Date')
    return_reason = fields.Char(string='Last Return Reason')
    returned_from_id = fields.Many2one('res.partner', string='Last Returned From')
    previous_owner = fields.Char(string='Previous Owner')
    previous_issue_date = fields.Date(string='Previous Issue Date')

    # Disposal Information
    disposal_date = fields.Date(string='Disposal Date')
    disposal_price = fields.Monetary(string='Disposal Price', currency_field='currency_id')
    sold_to_id = fields.Many2one('res.partner', string='Sold To / Scrapped By')
    disposal_notes = fields.Text(string='Disposal Reason / Notes')

    # General
    notes = fields.Html(string='Internal Notes')
    link = fields.Char(string='Reference Link / Document')

    @api.model
    def _default_stage_id(self):
        return self.env['it.asset.stage'].search([('stage_type', '=', 'stock')], limit=1).id

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env['it.asset.stage'].search([])

    @api.depends('stage_id', 'stage_id.stage_type', 'assigned_to_id')
    def _compute_is_assigned(self):
        for asset in self:
            asset.is_assigned = bool(asset.stage_id.stage_type == 'assigned' or asset.assigned_to_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ref') or vals.get('ref') == _('New'):
                vals['ref'] = self.env['ir.sequence'].next_by_code('it.asset.code') or _('New')
            if 'name' not in vals or not vals.get('name'):
                type_name = dict(self._fields['asset_type'].selection).get(vals.get('asset_type', 'laptop'), 'Asset')
                vals['name'] = f"{type_name} - {vals.get('ref', '')}"
            if vals.get('assigned_to_id'):
                vals['has_been_assigned'] = True
                if vals.get('condition') in ['new', False]:
                    vals['condition'] = 'used'
        return super(ItAsset, self).create(vals_list)

    def write(self, vals):
        if vals.get('assigned_to_id'):
            vals['has_been_assigned'] = True
            if 'condition' not in vals:
                for asset in self:
                    if asset.condition == 'new':
                        vals['condition'] = 'used'
                        break
        return super(ItAsset, self).write(vals)

    @api.constrains('condition', 'has_been_assigned')
    def _check_condition_history(self):
        for asset in self:
            if asset.has_been_assigned and asset.condition == 'new':
                raise UserError(_(
                    "Asset '%s' has already been assigned in custody before and cannot be set back to 'New'. "
                    "Physical condition must be 'Used', 'Fair', or 'Damaged'."
                ) % asset.name)

    def action_confirm(self):
        """Confirms asset details and locks specifications into read-only state."""
        for asset in self:
            asset.state = 'confirmed'
            asset.message_post(body=_("Asset details confirmed and locked."))

    def action_set_to_draft(self):
        """Only IT Managers / Administrators can unlock and set back to Draft."""
        if not self.env.user.has_group('it_asset_management.group_it_asset_manager') and not self.env.is_admin():
            raise UserError(_("Only IT Asset Managers or Administrators can reset an asset back to Draft."))
        for asset in self:
            asset.state = 'draft'
            asset.message_post(body=_("Asset status reset to Draft by %s.") % self.env.user.name)

    def action_set_to_stock(self):
        stock_stage = self.env['it.asset.stage'].search([('stage_type', '=', 'stock')], limit=1)
        for asset in self:
            vals = {
                'returned': True,
                'assigned_to_id': False,
                'current_assignment_id': False,
            }
            if stock_stage:
                vals['stage_id'] = stock_stage.id
            asset.write(vals)

    def action_assign_wizard(self):
        self.ensure_one()
        return {
            'name': _('Assign IT Asset'),
            'type': 'ir.actions.act_window',
            'res_model': 'it.asset.assign',
            'view_mode': 'form',
            'context': {
                'default_main_asset_id': self.id,
                'default_asset_ids': [(6, 0, [self.id])],
            },
            'target': 'current',
        }
