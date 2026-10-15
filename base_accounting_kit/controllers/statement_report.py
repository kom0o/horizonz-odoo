# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Aysha Shalin (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC
#    LICENSE (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
import json
import logging
from odoo import http
from odoo.http import content_disposition, request
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class XLSXReportController(http.Controller):
    """ Controller for xlsx report """

    @http.route('/xlsx_report', type='http', auth='user', methods=['POST'],
                csrf=False)
    def get_report_xlsx(self, model=None, data=None, output_format='xlsx', report_name='Report',
                        report_action=None, **kw):
        """Generate an XLSX report based on the provided data and return it as
        a response.
        """
        # Resolve parameters from kw if not provided as named args
        if not model and 'model' in kw:
            model = kw.get('model')
        if not data:
            data = kw.get('data') or kw.get('options')
        if not output_format and 'output_format' in kw:
            output_format = kw.get('output_format', 'xlsx')
        if not report_name or report_name == 'Report':
            report_name = kw.get('report_name') or report_name or 'Report'
        if not report_action and 'report_action' in kw:
            report_action = kw.get('report_action')

        uid = request.session.uid
        report_obj = request.env[model].with_user(uid)
        token = 'dummy-because-api-expects-one'
        try:
            if output_format == 'xlsx':
                response = request.make_response(
                    None,
                    headers=[
                        ('Content-Type', 'application/vnd.ms-excel'),
                        ('Content-Disposition',
                         content_disposition((report_name or 'Report') + '.xlsx'))
                    ]
                )
                try:
                    report_obj.get_xlsx_report(data, response, report_name, report_action)
                except TypeError:
                    report_obj.get_xlsx_report(data, response)

            response.set_cookie('fileToken', token)
            return response
        except Exception as e:
            _logger.exception("Error generating XLSX report: %s", str(e))
            se = http.serialize_exception(e)
            error = {
                'code': 200,
                'message': 'Odoo Server Error',
                'data': se
            }
            return request.make_response(html_escape(json.dumps(error)))
