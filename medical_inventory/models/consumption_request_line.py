from odoo import models, fields, api


class ConsumptionRequestLine(models.Model):
    _name = 'medical.consumption.request.line'
    _description = 'Medical Consumption Request Line'

    request_id = fields.Many2one(
        'medical.consumption.request', string='Request',
        required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain=[('type', 'in', ['product', 'consu'])])
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    available_qty = fields.Float(string='Available', compute='_compute_available_qty')
    notes = fields.Char(string='Note')

    # Stored related fields for analytics
    department_location_id = fields.Many2one(
        'stock.location', string='Clinic',
        related='request_id.department_location_id', store=True)
    date_request = fields.Datetime(
        string='Date', related='request_id.date_request', store=True)
    request_type = fields.Selection(
        related='request_id.request_type', store=True, string='Type')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id

    @api.depends('product_id', 'request_id.department_location_id',
                 'request_id.source_location_id', 'request_id.request_type')
    def _compute_available_qty(self):
        for line in self:
            location = (
                line.request_id.source_location_id
                if line.request_id.request_type == 'transfer'
                else line.request_id.department_location_id
            )
            if line.product_id and location:
                quant = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', location.id),
                ], limit=1)
                line.available_qty = quant.quantity if quant else 0.0
            else:
                line.available_qty = 0.0

    def _get_products_in_location(self, location_id):
        """Return product IDs that have stock in the given location."""
        if not location_id:
            return []
        quants = self.env['stock.quant'].search([
            ('location_id', '=', location_id),
            ('quantity', '>', 0),
        ])
        return quants.mapped('product_id').ids
