from odoo import models, fields, api, _
import urllib.parse as parse

class SendContactMessage(models.TransientModel):
    _name = 'whatsapp.wizard.contact'
    _description = 'WhatsApp Contact Message Wizard'

    user_id = fields.Many2one('res.partner', string="Recipient Name", default=lambda self: self.env[self._context.get('active_model')].browse(self.env.context.get('active_ids')))
    mobile_number = fields.Char(related='user_id.mobile', required=True)
    message = fields.Text(string="Message", required=True)

    def send_custom_contact_message(self):
        if self.message:
            message_string = parse.quote(self.message)
            number = self.user_id.mobile
            link = "https://web.whatsapp.com/send?phone=" + number
            send_msg = {
                'type': 'ir.actions.act_url',
                'url': link + "&text=" + message_string,
                'target': 'new',
                'res_id': self.id,
            }
            return send_msg
