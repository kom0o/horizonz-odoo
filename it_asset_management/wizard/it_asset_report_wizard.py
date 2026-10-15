# -*- coding: utf-8 -*-
import io
import base64
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class ItAssetReportWizard(models.TransientModel):
    _name = 'it.asset.report.wizard'
    _description = 'IT Assets Inventory & Custody Excel Report Wizard'

    # Filter Parameters
    employee_id = fields.Many2one(
        'res.partner',
        string='Employee / Custodian',
        help='Filter by assigned employee or custody holder.'
    )
    include_history = fields.Boolean(
        string='Include Past Custody / Returns for this Employee',
        default=False,
        help='If checked, also includes assets previously returned or purchased by this employee.'
    )
    location_id = fields.Many2one(
        'it.asset.location',
        string='Physical Location',
        help='Filter by physical branch, factory, or facility.'
    )
    date_filter_type = fields.Selection([
        ('acquisition_date', 'Acquisition Date (تاريخ الشراء)'),
        ('assign_date', 'Custody Assignment Date (تاريخ تسليم العهدة)'),
        ('return_date', 'Return Date (تاريخ الاسترجاع)'),
        ('disposal_date', 'Disposal Date (تاريخ التخريد/البيع)'),
        ('any', 'Any Lifecycle Movement (أي حركة)'),
    ], string='Date Filter Field', default='acquisition_date', required=True)
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    lifecycle_filter = fields.Selection([
        ('all', 'All Lifecycle Statuses'),
        ('stock', 'In Stock (Available)'),
        ('assigned', 'In Custody (Assigned)'),
        ('returned', 'Returned Assets'),
        ('scrap', 'Scrapped / Loss / Damaged'),
        ('sold', 'Sold / Liquidated'),
    ], string='Lifecycle Status', default='all', required=True)

    stage_id = fields.Many2one('it.asset.stage', string='Specific Stage')

    condition = fields.Selection([
        ('all', 'All Conditions'),
        ('new', 'New'),
        ('good', 'Good / Used'),
        ('fair', 'Fair'),
        ('damaged', 'Damaged / Needs Repair'),
    ], string='Physical Condition', default='all', required=True)

    asset_type = fields.Selection([
        ('all', 'All Asset Types'),
        ('laptop', 'Laptop'),
        ('pc', 'PC / Desktop'),
        ('screen', 'Screen / Monitor'),
        ('all_in_one', 'All-In-One'),
        ('tablet', 'Tablet'),
        ('printer', 'Printer'),
        ('keyboard', 'Keyboard'),
        ('mouse', 'Mouse'),
        ('other', 'Other'),
    ], string='Asset Type', default='all', required=True)

    # State & Download Fields
    excel_file = fields.Binary(string='Excel File', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)
    state = fields.Selection([
        ('choose', 'choose'),
        ('get', 'get'),
    ], default='choose')

    def action_generate_excel_report(self):
        """Build domain from wizard filters, generate styled Excel workbook, and return download action."""
        self.ensure_one()
        domain = []

        # 1. Location filter
        if self.location_id:
            domain.append(('asset_location_id', '=', self.location_id.id))

        # 2. Employee filter
        if self.employee_id:
            if self.include_history:
                domain.extend([
                    '|', ('assigned_to_id', '=', self.employee_id.id),
                    '|', ('returned_from_id', '=', self.employee_id.id),
                    ('sold_to_id', '=', self.employee_id.id)
                ])
            else:
                domain.append(('assigned_to_id', '=', self.employee_id.id))

        # 3. Lifecycle Status filter
        if self.lifecycle_filter == 'stock':
            domain.append(('stage_id.stage_type', '=', 'stock'))
        elif self.lifecycle_filter == 'assigned':
            domain.append(('stage_id.stage_type', '=', 'assigned'))
        elif self.lifecycle_filter == 'returned':
            domain.append(('returned', '=', True))
        elif self.lifecycle_filter == 'scrap':
            domain.append(('stage_id.stage_type', '=', 'scrap'))
        elif self.lifecycle_filter == 'sold':
            domain.append(('stage_id.stage_type', '=', 'sold'))

        # 4. Stage filter
        if self.stage_id:
            domain.append(('stage_id', '=', self.stage_id.id))

        # 5. Condition filter
        if self.condition != 'all':
            domain.append(('condition', '=', self.condition))

        # 6. Asset type filter
        if self.asset_type != 'all':
            domain.append(('asset_type', '=', self.asset_type))

        # 7. Date range filter
        if self.date_from or self.date_to:
            if self.date_filter_type == 'any':
                date_subdomain = []
                for field_name in ['acquisition_date', 'assign_date', 'return_date', 'disposal_date']:
                    clause = []
                    if self.date_from:
                        clause.append((field_name, '>=', self.date_from))
                    if self.date_to:
                        clause.append((field_name, '<=', self.date_to))
                    date_subdomain.append(clause)
                # Combine with OR: (| (| (a) (b)) (c))
                combined = date_subdomain[0]
                for next_clause in date_subdomain[1:]:
                    combined = ['|'] * len(next_clause) + combined + next_clause
                domain.extend(combined)
            else:
                field_name = self.date_filter_type
                if self.date_from:
                    domain.append((field_name, '>=', self.date_from))
                if self.date_to:
                    domain.append((field_name, '<=', self.date_to))

        assets = self.env['it.asset'].search(domain, order='ref asc, id asc')

        # Generate workbook in memory
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._build_excel_sheets(workbook, assets)
        workbook.close()
        output.seek(0)
        file_data = output.read()

        report_timestamp = fields.Datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"IT_Assets_Report_{report_timestamp}.xlsx"

        # Create attachment for direct download
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'res_model': 'it.asset.report.wizard',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        self.write({
            'excel_file': base64.b64encode(file_data),
            'file_name': filename,
            'state': 'get',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _build_excel_sheets(self, workbook, assets):
        """Constructs both the Master Inventory sheet and Executive Summary sheet."""
        # Common Palette & Styles
        title_style = workbook.add_format({
            'bold': True, 'font_size': 16, 'font_name': 'Segoe UI',
            'font_color': '#FFFFFF', 'bg_color': '#0F4C81',
            'align': 'center', 'valign': 'vcenter'
        })
        subtitle_style = workbook.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'italic': True,
            'font_color': '#E2E8F0', 'bg_color': '#0F4C81',
            'align': 'center', 'valign': 'vcenter'
        })
        card_label_style = workbook.add_format({
            'bold': True, 'font_size': 8, 'font_name': 'Segoe UI',
            'font_color': '#475569', 'bg_color': '#F1F5F9',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#CBD5E1'
        })
        card_val_style = workbook.add_format({
            'bold': True, 'font_size': 11, 'font_name': 'Segoe UI',
            'font_color': '#0F4C81', 'bg_color': '#FFFFFF',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#CBD5E1'
        })
        card_val_money = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI',
            'font_color': '#0F4C81', 'bg_color': '#FFFFFF',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#CBD5E1',
            'num_format': '#,##0.00'
        })
        filter_box_style = workbook.add_format({
            'font_size': 8, 'font_name': 'Segoe UI',
            'font_color': '#334155', 'bg_color': '#F8FAFC',
            'border': 1, 'border_color': '#E2E8F0', 'valign': 'vcenter'
        })
        filter_box_bold = workbook.add_format({
            'bold': True, 'font_size': 8, 'font_name': 'Segoe UI',
            'font_color': '#0F4C81', 'bg_color': '#F8FAFC',
            'border': 1, 'border_color': '#E2E8F0', 'valign': 'vcenter'
        })

        header_style = workbook.add_format({
            'bold': True, 'font_size': 9, 'font_name': 'Segoe UI',
            'font_color': '#FFFFFF', 'bg_color': '#1B365D',
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            'border': 1, 'border_color': '#1B365D'
        })

        # Cell Formats - Standard (Even rows)
        c_left = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'align': 'left', 'valign': 'vcenter', 'border': 1, 'border_color': '#E2E8F0'})
        c_center = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#E2E8F0'})
        c_right = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'align': 'right', 'valign': 'vcenter', 'border': 1, 'border_color': '#E2E8F0'})
        c_date = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'align': 'center', 'valign': 'vcenter', 'num_format': 'yyyy-mm-dd', 'border': 1, 'border_color': '#E2E8F0'})
        c_money = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00', 'border': 1, 'border_color': '#E2E8F0'})

        # Cell Formats - Zebra (Odd rows)
        z_bg = '#F8FAFC'
        z_left = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': z_bg, 'align': 'left', 'valign': 'vcenter', 'border': 1, 'border_color': '#E2E8F0'})
        z_center = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': z_bg, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#E2E8F0'})
        z_right = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': z_bg, 'align': 'right', 'valign': 'vcenter', 'border': 1, 'border_color': '#E2E8F0'})
        z_date = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': z_bg, 'align': 'center', 'valign': 'vcenter', 'num_format': 'yyyy-mm-dd', 'border': 1, 'border_color': '#E2E8F0'})
        z_money = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': z_bg, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00', 'border': 1, 'border_color': '#E2E8F0'})

        # Status & Condition Badges
        badge_stock = workbook.add_format({'bold': True, 'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#D1E7DD', 'font_color': '#0F5132', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#BADBCC'})
        badge_assigned = workbook.add_format({'bold': True, 'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#CFE2FF', 'font_color': '#084298', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#B6D4FE'})
        badge_scrap = workbook.add_format({'bold': True, 'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#F8D7DA', 'font_color': '#842029', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#F5C2C7'})
        badge_sold = workbook.add_format({'bold': True, 'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#E2E3E5', 'font_color': '#41464B', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#D3D6D8'})

        badge_cond_new = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#ECFDF5', 'font_color': '#065F46', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#A7F3D0'})
        badge_cond_good = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#EFF6FF', 'font_color': '#1E40AF', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#BFDBFE'})
        badge_cond_fair = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#FFFBEB', 'font_color': '#92400E', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#FDE68A'})
        badge_cond_damaged = workbook.add_format({'font_size': 9, 'font_name': 'Segoe UI', 'bg_color': '#FEF2F2', 'font_color': '#991B1B', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#FECACA'})

        total_label_style = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI',
            'font_color': '#0F172A', 'bg_color': '#E2E8F0',
            'align': 'right', 'valign': 'vcenter', 'border': 1, 'border_color': '#94A3B8'
        })
        total_money_style = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI',
            'font_color': '#0F4C81', 'bg_color': '#E2E8F0',
            'align': 'right', 'valign': 'vcenter', 'border': 1, 'border_color': '#94A3B8',
            'num_format': '#,##0.00'
        })
        total_count_style = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI',
            'font_color': '#0F4C81', 'bg_color': '#E2E8F0',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#94A3B8'
        })

        # ==========================================
        # SHEET 1: Master Asset Inventory
        # ==========================================
        sheet = workbook.add_worksheet('Asset Inventory')
        sheet.set_margins(left=0.4, right=0.4, top=0.5, bottom=0.5)

        # 1. Main Header Title
        sheet.merge_range('A1:AC1', 'HORIZONZ IT ASSET MANAGEMENT & DIGITAL CUSTODY REPORT', title_style)
        sheet.set_row(0, 30)

        # Subtitle
        print_date_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M')
        user_name = self.env.user.name or 'Administrator'
        sheet.merge_range('A2:AC2', f"Generated on {print_date_str} by {user_name} | Horizonz Cloud Solutions", subtitle_style)
        sheet.set_row(1, 18)

        # 2. KPI Summary Cards (Row 4 & 5)
        total_count = len(assets)
        stock_count = sum(1 for a in assets if a.stage_type == 'stock')
        assigned_count = sum(1 for a in assets if a.stage_type == 'assigned')
        returned_count = sum(1 for a in assets if a.returned)
        scrap_count = sum(1 for a in assets if a.stage_type == 'scrap')
        sold_count = sum(1 for a in assets if a.stage_type == 'sold')
        total_acq_value = sum(a.acquisition_price for a in assets)

        sheet.set_row(3, 16)
        sheet.set_row(4, 22)

        kpis = [
            ('A4', 'B4', 'A5', 'B5', 'TOTAL ASSETS', total_count, card_val_style),
            ('D4', 'E4', 'D5', 'E5', 'IN STOCK (AVAILABLE)', stock_count, card_val_style),
            ('G4', 'H4', 'G5', 'H5', 'CURRENTLY ASSIGNED', assigned_count, card_val_style),
            ('J4', 'K4', 'J5', 'K5', 'RETURNED ASSETS', returned_count, card_val_style),
            ('M4', 'N4', 'M5', 'N5', 'SCRAPPED / LOST', scrap_count, card_val_style),
            ('P4', 'Q4', 'P5', 'Q5', 'SOLD / LIQUIDATED', sold_count, card_val_style),
            ('S4', 'U4', 'S5', 'U5', 'TOTAL ACQUISITION (SAR)', total_acq_value, card_val_money),
        ]
        for t1, t2, v1, v2, label, val, val_fmt in kpis:
            sheet.merge_range(f'{t1}:{t2}', label, card_label_style)
            sheet.merge_range(f'{v1}:{v2}', val, val_fmt)

        # 3. Parameters / Active Filters Summary (Row 7 & 8)
        sheet.set_row(6, 18)
        sheet.set_row(7, 18)

        emp_label = self.employee_id.name if self.employee_id else 'All Employees / Custodians'
        if self.employee_id and self.include_history:
            emp_label += ' (Includes Past Returns/Sales)'
        loc_label = self.location_id.name if self.location_id else 'All Locations / Facilities'
        life_dict = dict(self._fields['lifecycle_filter'].selection)
        life_label = life_dict.get(self.lifecycle_filter, 'All')
        cond_dict = dict(self._fields['condition'].selection)
        cond_label = cond_dict.get(self.condition, 'All')

        d_from = str(self.date_from) if self.date_from else 'Start'
        d_to = str(self.date_to) if self.date_to else 'End'
        date_label = f"{d_from} to {d_to} ({dict(self._fields['date_filter_type'].selection).get(self.date_filter_type)})"

        sheet.write('A7', 'Location Filter:', filter_box_bold)
        sheet.write('B7', loc_label, filter_box_style)
        sheet.write('D7', 'Employee Filter:', filter_box_bold)
        sheet.merge_range('E7:G7', emp_label, filter_box_style)
        sheet.write('I7', 'Date Range:', filter_box_bold)
        sheet.merge_range('J7:L7', date_label, filter_box_style)

        sheet.write('A8', 'Lifecycle Filter:', filter_box_bold)
        sheet.write('B8', life_label, filter_box_style)
        sheet.write('D8', 'Condition Filter:', filter_box_bold)
        sheet.merge_range('E8:G8', cond_label, filter_box_style)
        sheet.write('I8', 'Asset Type:', filter_box_bold)
        sheet.merge_range('J8:L8', dict(self._fields['asset_type'].selection).get(self.asset_type, 'All'), filter_box_style)

        # 4. Table Headers (Row 10, index 9)
        header_row = 9
        sheet.set_row(header_row, 30)

        columns = [
            ('#', 5),
            ('Asset Code', 12),
            ('Asset Name / Description', 28),
            ('Asset Type', 14),
            ('Lifecycle Stage', 15),
            ('Physical Condition', 15),
            ('Physical Location', 20),
            ('Current Custodian (Employee)', 24),
            ('Employee Code', 14),
            ('Department', 18),
            ('Custody Assign Date', 14),
            ('Serial Number', 18),
            ('Model & SKU', 18),
            ('CPU / Processor', 16),
            ('RAM', 10),
            ('Storage', 16),
            ('Peripherals Included', 18),
            ('Operating System', 16),
            ('Office / Licenses', 18),
            ('Acquisition Date', 14),
            ('Acquisition Price (SAR)', 16),
            ('Warranty', 14),
            ('Returned?', 12),
            ('Last Return Date', 14),
            ('Returned From', 22),
            ('Return Reason', 22),
            ('Disposal Disposition', 16),
            ('Disposal Date', 14),
            ('Disposal Price (SAR)', 16),
            ('Sold To / Liquidator', 22),
            ('Disposal Notes', 26),
        ]

        for col_idx, (col_name, col_width) in enumerate(columns):
            sheet.write(header_row, col_idx, col_name, header_style)
            sheet.set_column(col_idx, col_idx, col_width)

        # 5. Populate Data Rows
        row_idx = header_row + 1
        asset_type_dict = dict(self.env['it.asset']._fields['asset_type'].selection)
        cond_dict = dict(self.env['it.asset']._fields['condition'].selection)

        for i, asset in enumerate(assets, 1):
            is_zebra = (i % 2 == 0)
            fl = z_left if is_zebra else c_left
            fc = z_center if is_zebra else c_center
            fr = z_right if is_zebra else c_right
            fd = z_date if is_zebra else c_date
            fm = z_money if is_zebra else c_money

            sheet.set_row(row_idx, 20)

            # 1: #
            sheet.write(row_idx, 0, i, fc)
            # 2: Asset Code
            sheet.write(row_idx, 1, asset.ref or '', fc)
            # 3: Asset Name
            sheet.write(row_idx, 2, asset.name or '', fl)
            # 4: Asset Type
            sheet.write(row_idx, 3, asset_type_dict.get(asset.asset_type, asset.asset_type or ''), fc)

            # 5: Lifecycle Stage (Colored badge)
            stage_name = asset.stage_id.name or (asset.stage_type or '').title()
            if asset.stage_type == 'stock':
                sheet.write(row_idx, 4, stage_name, badge_stock)
            elif asset.stage_type == 'assigned':
                sheet.write(row_idx, 4, stage_name, badge_assigned)
            elif asset.stage_type == 'scrap':
                sheet.write(row_idx, 4, stage_name, badge_scrap)
            elif asset.stage_type == 'sold':
                sheet.write(row_idx, 4, stage_name, badge_sold)
            else:
                sheet.write(row_idx, 4, stage_name, fc)

            # 6: Physical Condition (Colored badge)
            cond_label = cond_dict.get(asset.condition, asset.condition or '')
            if asset.condition == 'new':
                sheet.write(row_idx, 5, cond_label, badge_cond_new)
            elif asset.condition == 'good':
                sheet.write(row_idx, 5, cond_label, badge_cond_good)
            elif asset.condition == 'fair':
                sheet.write(row_idx, 5, cond_label, badge_cond_fair)
            elif asset.condition == 'damaged':
                sheet.write(row_idx, 5, cond_label, badge_cond_damaged)
            else:
                sheet.write(row_idx, 5, cond_label, fc)

            # 7: Location
            sheet.write(row_idx, 6, asset.asset_location_id.name or '-', fl)

            # 8: Current Custodian / Employee
            sheet.write(row_idx, 7, asset.assigned_to_id.name or '-', fl)
            # 9: Employee Code
            sheet.write(row_idx, 8, asset.assigned_to_id.employee_code or '-', fc)
            # 10: Department
            sheet.write(row_idx, 9, asset.assigned_to_id.it_department_name or '-', fl)
            # 11: Custody Assign Date
            if asset.assign_date:
                sheet.write(row_idx, 10, str(asset.assign_date), fd)
            else:
                sheet.write(row_idx, 10, '-', fc)

            # 12: Serial Number
            sheet.write(row_idx, 11, asset.serial_no or '-', fc)
            # 13: Model & SKU
            sheet.write(row_idx, 12, asset.model_sku or '-', fl)
            # 14: CPU
            sheet.write(row_idx, 13, asset.cpu or '-', fc)
            # 15: RAM
            sheet.write(row_idx, 14, asset.ram or '-', fc)

            # 16: Storage (Combine NVMe, SSD, HDD)
            storages = []
            if asset.nvme:
                storages.append(f"NVMe: {asset.nvme}")
            if asset.ssd:
                storages.append(f"SSD: {asset.ssd}")
            if asset.hdd:
                storages.append(f"HDD: {asset.hdd}")
            sheet.write(row_idx, 15, ' | '.join(storages) if storages else '-', fl)

            # 17: Peripherals
            periph = []
            if asset.keyboard_included:
                periph.append('Keyboard')
            if asset.mouse_included:
                periph.append('Mouse')
            sheet.write(row_idx, 16, ', '.join(periph) if periph else 'None', fc)

            # 18: OS
            sheet.write(row_idx, 17, asset.os or '-', fl)
            # 19: Licenses / Software
            licenses = []
            if asset.ms_office:
                licenses.append(f"Office: {asset.ms_office}")
            if asset.anti_virus:
                licenses.append(f"AV: {asset.anti_virus}")
            sheet.write(row_idx, 18, ' | '.join(licenses) if licenses else '-', fl)

            # 20: Acquisition Date
            if asset.acquisition_date:
                sheet.write(row_idx, 19, str(asset.acquisition_date), fd)
            else:
                sheet.write(row_idx, 19, '-', fc)

            # 21: Acquisition Price
            sheet.write(row_idx, 20, asset.acquisition_price or 0.0, fm)

            # 22: Warranty
            sheet.write(row_idx, 21, asset.warranty_status or '-', fc)

            # 23: Returned?
            sheet.write(row_idx, 22, 'Yes' if asset.returned else 'No', fc)
            # 24: Last Return Date
            if asset.return_date:
                sheet.write(row_idx, 23, str(asset.return_date), fd)
            else:
                sheet.write(row_idx, 23, '-', fc)
            # 25: Returned From
            sheet.write(row_idx, 24, asset.returned_from_id.name or '-', fl)
            # 26: Return Reason
            sheet.write(row_idx, 25, asset.return_reason or '-', fl)

            # 27: Disposal Disposition
            if asset.stage_type == 'scrap':
                sheet.write(row_idx, 26, 'Scrap / Loss', badge_scrap)
            elif asset.stage_type == 'sold':
                sheet.write(row_idx, 26, 'Sold / Liquidated', badge_sold)
            else:
                sheet.write(row_idx, 26, 'Active / In Service', fc)

            # 28: Disposal Date
            if asset.disposal_date:
                sheet.write(row_idx, 27, str(asset.disposal_date), fd)
            else:
                sheet.write(row_idx, 27, '-', fc)

            # 29: Disposal Price
            sheet.write(row_idx, 28, asset.disposal_price or 0.0, fm)

            # 30: Sold To / Merchant
            sheet.write(row_idx, 29, asset.sold_to_id.name or '-', fl)

            # 31: Disposal Notes
            sheet.write(row_idx, 30, asset.disposal_notes or '-', fl)

            row_idx += 1

        # Summary Row at bottom
        sheet.set_row(row_idx, 24)
        sheet.merge_range(f'A{row_idx + 1}:C{row_idx + 1}', 'TOTAL SUMMARY', total_label_style)
        sheet.write(row_idx, 3, f"{len(assets)} Assets", total_count_style)
        for col_fill in range(4, 20):
            sheet.write(row_idx, col_fill, '', total_label_style)
        # Sum acquisition price
        first_data_row = header_row + 2
        last_data_row = row_idx
        if len(assets) > 0:
            sheet.write_formula(row_idx, 20, f'=SUM(U{first_data_row}:U{last_data_row})', total_money_style)
        else:
            sheet.write(row_idx, 20, 0.0, total_money_style)

        for col_fill in range(21, 28):
            sheet.write(row_idx, col_fill, '', total_label_style)

        # Sum disposal price
        if len(assets) > 0:
            sheet.write_formula(row_idx, 28, f'=SUM(AC{first_data_row}:AC{last_data_row})', total_money_style)
        else:
            sheet.write(row_idx, 28, 0.0, total_money_style)

        sheet.write(row_idx, 29, '', total_label_style)
        sheet.write(row_idx, 30, '', total_label_style)

        # Freeze panes at data row (row 11, col 2 -> freezes ref & name!)
        sheet.freeze_panes(header_row + 1, 3)

        # Enable Auto-Filter on data columns
        sheet.autofilter(header_row, 0, row_idx - 1, len(columns) - 1)

        # ==========================================
        # SHEET 2: Executive Breakdown & Analytics
        # ==========================================
        sum_sheet = workbook.add_worksheet('Executive Summary')
        sum_sheet.set_margins(left=0.5, right=0.5, top=0.5, bottom=0.5)

        sum_sheet.merge_range('A1:G1', 'IT ASSET MANAGEMENT - EXECUTIVE BREAKDOWN', title_style)
        sum_sheet.set_row(0, 28)
        sum_sheet.merge_range('A2:G2', f'Inventory Distribution as of {print_date_str}', subtitle_style)
        sum_sheet.set_row(1, 16)

        sub_header = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI',
            'font_color': '#FFFFFF', 'bg_color': '#0F4C81',
            'align': 'center', 'valign': 'vcenter', 'border': 1
        })
        sec_title = workbook.add_format({
            'bold': True, 'font_size': 11, 'font_name': 'Segoe UI',
            'font_color': '#0F4C81', 'bottom': 2, 'bottom_color': '#0F4C81'
        })

        # Table 1: Breakdown by Lifecycle Stage
        curr_r = 4
        sum_sheet.write(curr_r, 0, '1. Lifecycle Stage Distribution', sec_title)
        curr_r += 1
        sum_sheet.write(curr_r, 0, 'Stage', sub_header)
        sum_sheet.write(curr_r, 1, 'Stage Type', sub_header)
        sum_sheet.write(curr_r, 2, 'Count', sub_header)
        sum_sheet.write(curr_r, 3, '% of Total', sub_header)
        sum_sheet.write(curr_r, 4, 'Total Value (SAR)', sub_header)
        curr_r += 1

        stage_groups = {}
        for a in assets:
            s_name = a.stage_id.name or (a.stage_type or '').title()
            s_type = a.stage_type or 'other'
            if s_name not in stage_groups:
                stage_groups[s_name] = {'type': s_type, 'count': 0, 'value': 0.0}
            stage_groups[s_name]['count'] += 1
            stage_groups[s_name]['value'] += (a.acquisition_price or 0.0)

        for s_name, data in sorted(stage_groups.items(), key=lambda x: x[1]['count'], reverse=True):
            pct = (data['count'] / total_count) * 100 if total_count else 0
            sum_sheet.write(curr_r, 0, s_name, c_left)
            sum_sheet.write(curr_r, 1, data['type'].title(), c_center)
            sum_sheet.write(curr_r, 2, data['count'], c_center)
            sum_sheet.write(curr_r, 3, f"{pct:.1f}%", c_center)
            sum_sheet.write(curr_r, 4, data['value'], c_money)
            curr_r += 1

        # Table 2: Breakdown by Physical Condition
        curr_r += 2
        sum_sheet.write(curr_r, 0, '2. Physical Condition Distribution', sec_title)
        curr_r += 1
        sum_sheet.write(curr_r, 0, 'Condition', sub_header)
        sum_sheet.write(curr_r, 1, 'Asset Count', sub_header)
        sum_sheet.write(curr_r, 2, '% of Total', sub_header)
        sum_sheet.write(curr_r, 3, 'Acquisition Value (SAR)', sub_header)
        curr_r += 1

        cond_groups = {}
        for a in assets:
            c_label = cond_dict.get(a.condition, a.condition or 'Unknown')
            if c_label not in cond_groups:
                cond_groups[c_label] = {'count': 0, 'value': 0.0}
            cond_groups[c_label]['count'] += 1
            cond_groups[c_label]['value'] += (a.acquisition_price or 0.0)

        for c_label, data in cond_groups.items():
            pct = (data['count'] / total_count) * 100 if total_count else 0
            sum_sheet.write(curr_r, 0, c_label, c_left)
            sum_sheet.write(curr_r, 1, data['count'], c_center)
            sum_sheet.write(curr_r, 2, f"{pct:.1f}%", c_center)
            sum_sheet.write(curr_r, 3, data['value'], c_money)
            curr_r += 1

        # Table 3: Breakdown by Top Locations
        curr_r += 2
        sum_sheet.write(curr_r, 0, '3. Facility & Branch Location Distribution', sec_title)
        curr_r += 1
        sum_sheet.write(curr_r, 0, 'Location', sub_header)
        sum_sheet.write(curr_r, 1, 'Hardware Count', sub_header)
        sum_sheet.write(curr_r, 2, '% Share', sub_header)
        sum_sheet.write(curr_r, 3, 'Inventory Value (SAR)', sub_header)
        curr_r += 1

        loc_groups = {}
        for a in assets:
            l_name = a.asset_location_id.name or 'Unassigned / Head Office'
            if l_name not in loc_groups:
                loc_groups[l_name] = {'count': 0, 'value': 0.0}
            loc_groups[l_name]['count'] += 1
            loc_groups[l_name]['value'] += (a.acquisition_price or 0.0)

        for l_name, data in sorted(loc_groups.items(), key=lambda x: x[1]['count'], reverse=True):
            pct = (data['count'] / total_count) * 100 if total_count else 0
            sum_sheet.write(curr_r, 0, l_name, c_left)
            sum_sheet.write(curr_r, 1, data['count'], c_center)
            sum_sheet.write(curr_r, 2, f"{pct:.1f}%", c_center)
            sum_sheet.write(curr_r, 3, data['value'], c_money)
            curr_r += 1

        # Adjust summary sheet column widths
        sum_sheet.set_column(0, 0, 30)
        sum_sheet.set_column(1, 1, 18)
        sum_sheet.set_column(2, 2, 16)
        sum_sheet.set_column(3, 3, 16)
        sum_sheet.set_column(4, 4, 22)
