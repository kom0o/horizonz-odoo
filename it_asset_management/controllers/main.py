# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class ItAssetWebhookController(http.Controller):

    @http.route('/api/it_asset/webhook/approve', type='json', auth='public', methods=['POST'], csrf=False)
    def webhook_approve_assignment(self, **post):
        """
        Incoming webhook receiver called by n8n when an employee confirms IT custody via WhatsApp.
        Expected JSON payload:
        {
            "record_id": 42,
            "status": "approved" (or "confirmed"),
            "token": "it_assets_secure_token" (optional security token)
        }
        """
        data = request.dispatcher.jsonrequest
        _logger.info("Received n8n webhook approval payload: %s", data)

        record_id = data.get('record_id')
        token = data.get('token')

        # Optional token verification if configured
        expected_token = request.env['ir.config_parameter'].sudo().get_param('it_asset.webhook_secret')
        if expected_token and token and token != expected_token:
            return {'success': False, 'error': 'Invalid security token'}

        if not record_id:
            return {'success': False, 'error': 'Missing record_id in payload'}

        assignment = request.env['it.asset.assign'].sudo().browse(int(record_id))
        if not assignment.exists():
            return {'success': False, 'error': f'Assignment record {record_id} does not exist'}

        if assignment.state == 'confirmed':
            return {'success': True, 'message': 'Assignment is already confirmed'}

        try:
            assignment.action_confirm()
            assignment.write({'whatsapp_status': 'approved'})
            assignment.message_post(body="Digital custody confirmation accepted via WhatsApp (n8n webhook).")
            return {
                'success': True,
                'message': f"Assignment {assignment.name} successfully confirmed for {assignment.assigned_to_id.name}",
                'state': assignment.state
            }
        except Exception as e:
            _logger.exception("Error executing custody approval for assignment ID %s: %s", record_id, str(e))
            return {'success': False, 'error': str(e)}
