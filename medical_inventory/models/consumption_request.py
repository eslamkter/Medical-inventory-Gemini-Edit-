from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta


class ConsumptionRequest(models.Model):
    _name = 'medical.consumption.request'
    _description = 'Medical Inventory Consumption Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc'

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    date_request = fields.Datetime(string='Request Date', default=fields.Datetime.now,
                                   required=True, tracking=True)
    requested_by = fields.Many2one('res.users', string='Requested By',
                                   default=lambda self: self.env.user, required=True, tracking=True)
    request_type = fields.Selection([
        ('transfer', 'Transfer to Clinic'),
        ('consumption', 'Consumption / Usage Report'),
    ], string='Request Type', default='transfer', required=True, tracking=True)
    department_location_id = fields.Many2one(
        'stock.location', string='Clinic / Department', required=True, tracking=True,
        domain=[('usage', '=', 'internal')])
    source_location_id = fields.Many2one(
        'stock.location', string='Take From (Warehouse/Store)',
        tracking=True, domain=[('usage', '=', 'internal')])
    notes = fields.Text(string='Notes / Reason')
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'),
        ('done', 'Done'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    line_ids = fields.One2many(
        'medical.consumption.request.line', 'request_id', string='Items')
    stock_picking_id = fields.Many2one(
        'stock.picking', string='Stock Transfer', readonly=True)
    approved_by = fields.Many2one(
        'res.users', string='Approved By', readonly=True, tracking=True)
    date_approved = fields.Datetime(string='Approval Date', readonly=True)
    available_product_ids = fields.Many2many(
        'product.product', compute='_compute_available_product_ids',
        string='Available Products')

    @api.depends('department_location_id', 'request_type')
    def _compute_available_product_ids(self):
        for rec in self:
            if rec.request_type == 'consumption' and rec.department_location_id:
                quants = self.env['stock.quant'].search([
                    ('location_id', '=', rec.department_location_id.id),
                    ('quantity', '>', 0),
                ])
                rec.available_product_ids = quants.mapped('product_id')
            else:
                rec.available_product_ids = self.env['product.product']

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'medical.consumption.request') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add at least one item before submitting.'))
            if rec.request_type == 'transfer' and not rec.source_location_id:
                raise UserError(_('Please select a source location for transfer requests.'))
            rec.state = 'submitted'

    def action_approve(self):
        for rec in self:
            rec.state = 'approved'
            rec.approved_by = self.env.user
            rec.date_approved = fields.Datetime.now()

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('Cannot cancel a completed request.'))
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_process_stock(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Request must be approved before processing.'))
        if self.request_type == 'transfer':
            self._do_transfer()
        else:
            self._do_consumption()
        self.state = 'done'
        return True

    def _do_transfer(self):
        """ خصم من المخزن الرئيسي وإضافة لمخزن العيادة """
        if not self.source_location_id:
            raise UserError(_('Source location is required for transfers.'))
        for line in self.line_ids:
            # التأكد إن المنتج قابل للتخزين في السيستم
            line.product_id.product_tmpl_id.sudo().write({'type': 'consu'})

            src_quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.source_location_id.id),
            ], limit=1)

            available = src_quant.quantity if src_quant else 0
            if available < line.quantity:
                raise UserError(_('Not enough stock for %s in %s. Available: %.2f') %
                                (line.product_id.name, self.source_location_id.name, available))

            # 1. خصم من المصدر
            src_quant.sudo().write({'quantity': src_quant.quantity - line.quantity})

            # 2. إضافة للوجهة (العيادة)
            dst_quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.department_location_id.id),
            ], limit=1)
            if dst_quant:
                dst_quant.sudo().write({'quantity': dst_quant.quantity + line.quantity})
            else:
                self.env['stock.quant'].sudo().create({
                    'product_id': line.product_id.id,
                    'location_id': self.department_location_id.id,
                    'quantity': line.quantity,
                })
        self.message_post(body=_('Transfer complete.'))

    def _do_consumption(self):
        """ خصم الاستهلاك من مخزن العيادة مباشرة """
        for line in self.line_ids:
            line.product_id.product_tmpl_id.sudo().write({'type': 'consu'})

            quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.department_location_id.id),
            ], limit=1)

            available = quant.quantity if quant else 0
            if available < line.quantity:
                raise UserError(_('Not enough stock in %s. Available: %.2f') %
                                (self.department_location_id.name, available))

            if quant:
                quant.sudo().write({'quantity': quant.quantity - line.quantity})
        self.message_post(body=_('Consumption recorded.'))

    def get_dashboard_data(self):
        """Called by dashboard JS via orm.call"""
        today = date.today()
        in_7 = today + timedelta(days=7)
        in_30 = today + timedelta(days=30)

        quants = self.env['stock.quant'].search([
            ('location_id.usage', '=', 'internal'), ('quantity', '>', 0),
        ])
        total_products = len(set(quants.mapped('product_id').ids))
        total_qty = sum(quants.mapped('quantity'))
        total_value = sum(q.quantity * (q.product_id.standard_price or 0) for q in quants)

        pending = self.env['medical.consumption.request'].search_count([('state', '=', 'submitted')])
        approved = self.env['medical.consumption.request'].search_count([('state', '=', 'approved')])

        expired = self.env['medical.stock.receive.line'].search_count([
            ('expiry_date', '!=', False), ('expiry_date', '<=', str(today)),
            ('receive_id.state', '=', 'done'),
        ])
        critical = self.env['medical.stock.receive.line'].search_count([
            ('expiry_date', '!=', False), ('expiry_date', '>', str(today)),
            ('expiry_date', '<=', str(in_7)), ('receive_id.state', '=', 'done'),
        ])

        receipts = self.env['medical.stock.receive'].search(
            [('state', '=', 'done')], order='date_receive desc', limit=5)
        receipts_data = [{
            'name': r.name,
            'date': r.date_receive.strftime('%d %b %Y') if r.date_receive else '',
            'vendor': r.vendor_id.name or 'Unknown',
            'location': r.destination_location_id.name or '',
            'value': r.total_value,
        } for r in receipts]

        locations = self.env['stock.location'].search([
            ('usage', '=', 'internal'), ('active', '=', True)
        ])
        loc_data = []
        for loc in locations:
            lq = self.env['stock.quant'].search([
                ('location_id', '=', loc.id), ('quantity', '>', 0)
            ])
            qty = round(sum(lq.mapped('quantity')), 1)
            loc_val = round(sum(q.quantity * (q.product_id.standard_price or 0) for q in lq), 2)
            loc_data.append({
                'name': loc.name,
                'product_count': len(set(lq.mapped('product_id').ids)),
                'total_qty': qty,
                'total_value': loc_val,
            })
        loc_data.sort(key=lambda x: x['total_qty'], reverse=True)

        expiry_lines = self.env['medical.stock.receive.line'].search([
            ('expiry_date', '!=', False), ('expiry_date', '<=', str(in_30)),
            ('receive_id.state', '=', 'done'),
        ], order='expiry_date asc', limit=8)
        expiry_items = [{
            'product': l.product_id.name,
            'qty': l.quantity,
            'expiry': l.expiry_date.strftime('%d %b %Y') if l.expiry_date else '',
            'days_left': (l.expiry_date - today).days if l.expiry_date else 0,
            'location': l.receive_id.destination_location_id.name or '',
            'expired': (l.expiry_date - today).days < 0 if l.expiry_date else False,
            'critical': 0 <= (l.expiry_date - today).days <= 7 if l.expiry_date else False,
        } for l in expiry_lines]

        from dateutil.relativedelta import relativedelta
        monthly_spend = []
        for i in range(5, -1, -1):
            month_start = (today.replace(day=1) - relativedelta(months=i))
            month_end = (month_start + relativedelta(months=1))
            month_receipts = self.env['medical.stock.receive'].search([
                ('state', '=', 'done'),
                ('date_receive', '>=', str(month_start)),
                ('date_receive', '<', str(month_end)),
            ])
            monthly_spend.append({
                'month': month_start.strftime('%b %Y'),
                'value': round(sum(r.total_value for r in month_receipts), 2),
                'count': len(month_receipts),
            })

        all_lines = self.env['medical.stock.receive.line'].search([
            ('receive_id.state', '=', 'done')
        ])
        product_spend = {}
        for l in all_lines:
            pid = l.product_id.id
            pname = l.product_id.name
            if pid not in product_spend:
                product_spend[pid] = {'name': pname, 'total': 0, 'qty': 0}
            product_spend[pid]['total'] += l.subtotal
            product_spend[pid]['qty'] += l.quantity
        top_products = sorted(product_spend.values(), key=lambda x: x['total'], reverse=True)[:5]
        for p in top_products:
            p['total'] = round(p['total'], 2)
            p['qty'] = round(p['qty'], 1)

        return {
            'total_products': total_products,
            'total_qty': round(total_qty, 0),
            'total_value': round(total_value, 2),
            'pending_requests': pending,
            'approved_requests': approved,
            'expired_count': expired,
            'critical_count': critical,
            'recent_receipts': receipts_data,
            'locations': loc_data[:12],
            'expiry_items': expiry_items,
            'monthly_spend': monthly_spend,
            'top_products': top_products,
        }


class ConsumptionRequestLine(models.Model):
    _name = 'medical.consumption.request.line'
    _description = 'Medical Inventory Consumption Request Line'

    request_id = fields.Many2one('medical.consumption.request', string='Request Reference', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit', related='product_id.uom_id', readonly=True)
    date_request = fields.Datetime(related='request_id.date_request', store=True, readonly=True)
    department_location_id = fields.Many2one(related='request_id.department_location_id', store=True, readonly=True)