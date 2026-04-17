from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MedicalStockReceive(models.Model):
    _name = 'medical.stock.receive'
    _description = 'Medical Stock Receive'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       default=lambda self: self.env['ir.sequence'].next_by_code('medical.stock.receive'))
    date_receive = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    received_by = fields.Many2one('res.users', string='Received By', default=lambda self: self.env.user)
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    vendor_invoice_ref = fields.Char(string='Vendor Invoice Ref')
    destination_location_id = fields.Many2one('stock.location', string='Destination Location', required=True,
                                              domain=[('usage', '=', 'internal')])
    line_ids = fields.One2many('medical.stock.receive.line', 'receive_id', string='Lines')

    total_value = fields.Float(string='Total Value', compute='_compute_total_value', store=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Received'), ('cancelled', 'Cancelled')], string='Status',
                             default='draft', tracking=True)

    @api.depends('line_ids.subtotal')
    def _compute_total_value(self):
        for record in self:
            record.total_value = sum(line.subtotal for line in record.line_ids)

    def action_receive(self):
        for record in self:
            if not record.destination_location_id:
                raise UserError("من فضلك اختر مكان الاستلام أولاً!")

            # مكان المورد (المنبع)
            source_location = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
            if not source_location:
                source_location = self.env['stock.location'].search([('usage', '=', 'supplier')], limit=1)

            for line in record.line_ids:
                if line.product_id:
                    # التأكد من خيار Track Inventory (is_storable)
                    if not line.product_id.is_storable:
                        raise UserError(
                            "المنتج '%s' غير معد للتخزين. فعل خيار 'Track Inventory' أولاً." % line.product_id.name)

                    # الطريقة المباشرة لضرب الرصيد في الـ On Hand (أودو 19)
                    # بننشئ الـ Move ونعمله Force Done فوراً
                    move = self.env['stock.move'].sudo().create({
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.quantity,
                        'product_uom': line.product_uom_id.id,
                        'location_id': source_location.id,
                        'location_dest_id': record.destination_location_id.id,
                        'description_picking': record.name,
                        'state': 'draft',
                    })

                    move._action_confirm()
                    move._action_assign()

                    # دي أهم نقطة: التأكيد على سطر الحركة الفعلي
                    if move.move_line_ids:
                        move.move_line_ids.write({'quantity': line.quantity, 'picked': True})
                    else:
                        self.env['stock.move.line'].sudo().create({
                            'move_id': move.id,
                            'product_id': line.product_id.id,
                            'quantity': line.quantity,
                            'product_uom_id': line.product_uom_id.id,
                            'location_id': source_location.id,
                            'location_dest_id': record.destination_location_id.id,
                            'picked': True,
                        })

                    move._action_done()

            record.state = 'done'

    def action_cancel(self):
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.state = 'draft'


class MedicalStockReceiveLine(models.Model):
    _name = 'medical.stock.receive.line'
    _description = 'Medical Stock Receive Line'

    receive_id = fields.Many2one('medical.stock.receive', ondelete='cascade')
    date_receive = fields.Date(related='receive_id.date_receive', string='Date', store=True)
    vendor_id = fields.Many2one('res.partner', related='receive_id.vendor_id', string='Vendor', store=True)
    destination_location_id = fields.Many2one('stock.location', related='receive_id.destination_location_id',
                                              string='Location', store=True)

    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity', default=1.0)
    unit_price = fields.Float(string='Unit Price')
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)
    product_uom_id = fields.Many2one('uom.uom', related='product_id.uom_id', readonly=False)

    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number')
    expiry_date = fields.Date(string='Expiry Date')
    notes = fields.Char(string='Notes')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.unit_price = self.product_id.standard_price

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price