from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MedicalStockReceive(models.Model):
    _name = 'medical.stock.receive'
    _description = 'Medical Inventory - Receive Stock'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_receive desc'

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    date_receive = fields.Datetime(string='Receive Date', default=fields.Datetime.now,
                                   required=True, tracking=True)
    received_by = fields.Many2one('res.users', string='Received By',
                                  default=lambda self: self.env.user, required=True)
    destination_location_id = fields.Many2one(
        'stock.location', string='Store Into', required=True, tracking=True,
        domain=[('usage', '=', 'internal')])
    vendor_id = fields.Many2one('res.partner', string='Vendor / Supplier')
    vendor_name = fields.Char(string='Vendor Name (if not in system)')
    vendor_invoice_ref = fields.Char(string='Invoice / Delivery Note Ref')
    notes = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'), ('done', 'Done'), ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    line_ids = fields.One2many('medical.stock.receive.line', 'receive_id', string='Items Received')
    total_value = fields.Float(string='Total Value', compute='_compute_total_value', store=True)

    @api.depends('line_ids.subtotal')
    def _compute_total_value(self):
        for rec in self:
            rec.total_value = sum(rec.line_ids.mapped('subtotal'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'medical.stock.receive') or _('New')
        return super().create(vals_list)

    @api.onchange('vendor_id')
    def _onchange_vendor_id(self):
        pass

    def action_receive(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please add at least one item before receiving.'))

        # Auto-convert any consumable products to storable so they can be tracked
        for line in self.line_ids:
            if line.product_id.type == 'consu':
                line.product_id.product_tmpl_id.sudo().write({'type': 'storable'})

        received = []
        skipped = []
        for line in self.line_ids:
            if line.product_id.type not in ('product', 'storable', 'consu'):
                skipped.append(line.product_id.name)
                continue
            quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.destination_location_id.id),
                ('lot_id', '=', line.lot_id.id if line.lot_id else False),
            ], limit=1)
            if quant:
                quant.sudo().write({'quantity': quant.quantity + line.quantity})
            else:
                self.env['stock.quant'].sudo().create({
                    'product_id': line.product_id.id,
                    'location_id': self.destination_location_id.id,
                    'quantity': line.quantity,
                    'lot_id': line.lot_id.id if line.lot_id else False,
                })
            received.append('%s x%s' % (line.product_id.name, line.quantity))

        self.state = 'done'

        msg_parts = [_('Stock received into %s.') % self.destination_location_id.name]
        if received:
            msg_parts.append(_('Added: %s') % ', '.join(received))
        if skipped:
            msg_parts.append(
                _('Skipped (not Storable - fix Product Type): %s') % ', '.join(skipped))

        self.message_post(body='<br/>'.join(msg_parts))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'medical.stock.receive',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('Cannot cancel a completed receipt.'))
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'


class MedicalStockReceiveLine(models.Model):
    _name = 'medical.stock.receive.line'
    _description = 'Medical Stock Receive Line'

    receive_id = fields.Many2one('medical.stock.receive', string='Receipt',
                                 required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain=[('type', 'in', ['product', 'consu'])])
    product_uom_id = fields.Many2one('uom.uom', string='Unit')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    unit_price = fields.Float(string='Unit Price', default=0.0)
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)
    lot_id = fields.Many2one('stock.lot', string='Batch / Lot',
                             domain="[('product_id', '=', product_id)]")
    expiry_date = fields.Datetime(string='Expiry Date')
    notes = fields.Char(string='Note')

    # Stored related fields for analytics
    date_receive = fields.Datetime(related='receive_id.date_receive', store=True, string='Date')
    destination_location_id = fields.Many2one(
        related='receive_id.destination_location_id', store=True, string='Location')
    vendor_id = fields.Many2one(related='receive_id.vendor_id', store=True, string='Vendor')

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
            if self.product_id.standard_price:
                self.unit_price = self.product_id.standard_price

    @api.onchange('lot_id')
    def _onchange_lot_id(self):
        if self.lot_id and hasattr(self.lot_id, 'expiration_date') and self.lot_id.expiration_date:
            self.expiry_date = self.lot_id.expiration_date
