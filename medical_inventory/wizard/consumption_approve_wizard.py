from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConsumptionApproveWizard(models.TransientModel):
    _name = 'medical.consumption.approve.wizard'
    _description = 'Approve or Reject Consumption Request'

    request_id = fields.Many2one(
        'medical.consumption.request', string='Request', required=True
    )
    action = fields.Selection([
        ('approve', 'Approve'),
        ('reject', 'Reject'),
    ], string='Action', required=True, default='approve')
    note = fields.Text(string='Comment / Reason')

    def action_confirm(self):
        self.ensure_one()
        if self.action == 'approve':
            self.request_id.action_approve()
            if self.note:
                self.request_id.message_post(body=_('Approved. Note: %s') % self.note)
        elif self.action == 'reject':
            self.request_id.action_reject()
            if self.note:
                self.request_id.message_post(body=_('Rejected. Reason: %s') % self.note)
        return {'type': 'ir.actions.act_window_close'}
