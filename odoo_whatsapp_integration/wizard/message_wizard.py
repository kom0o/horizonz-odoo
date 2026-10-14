from odoo import models, fields, api, _
import html2text
import urllib.parse as parse

class MessageError(models.TransientModel):
    _name = 'display.error.message'
    _description = 'Display Error Message'

    def get_message(self):
        if self.env.context.get("message", False):
            return self.env.context.get('message')
        return False

    name = fields.Text(string="Message", readonly=True, default=get_message)

class SendMessage(models.TransientModel):
    _name = 'whatsapp.wizard'
    _description = 'WhatsApp Message Wizard'

    user_id = fields.Many2one('res.partner', string="Recipient Name", default=lambda self: self.env[self._context.get('active_model')].browse(self.env.context.get('active_ids')).partner_id)
    mobile_number = fields.Char(related='user_id.mobile', required=True)
    message = fields.Text(string="Message")
    model = fields.Char('mail.template.model_id')
    template_id = fields.Many2one('mail.template', 'Use template', index=True)

    @api.onchange('template_id')
    def onchange_template_id_wrapper(self):
        self.ensure_one()
        if self.template_id:
            res_id = self._context.get('active_id') or 1
            rendered_body = self.template_id._render_field('body_html', [res_id])
            self.message = html2text.html2text(rendered_body.get(res_id, ''))

    def send_custom_message(self):
        if self.message and self.mobile_number:
            message_string = parse.quote(self.message)
            message_string = message_string[:(len(message_string) - 3)]
            number = self.user_id.mobile
            link = "https://web.whatsapp.com/send?phone=" + number
            send_msg = {
                'type': 'ir.actions.act_url',
                'url': link + "&text=" + message_string,
                'target': 'new',
                'res_id': self.id,
            }
            return send_msg
