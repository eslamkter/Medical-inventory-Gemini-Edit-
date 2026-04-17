from odoo import models, fields, api, _


class MedicalLocation(models.Model):
    _name = 'medical.location'
    _description = 'Medical Clinic / Department Location'
    _order = 'name'

    name = fields.Char(string='Clinic / Department Name', required=True)
    location_id = fields.Many2one(
        'stock.location', string='Linked Stock Location', readonly=True
    )
    location_type = fields.Selection([
        ('clinic', 'Clinic'),
        ('department', 'Department'),
        ('store', 'Main Store / Warehouse'),
        ('pharmacy', 'Pharmacy'),
        ('other', 'Other'),
    ], string='Type', required=True, default='clinic')
    responsible_id = fields.Many2one('res.users', string='Responsible Person')
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    current_stock_count = fields.Integer(
        string='Products in Stock', compute='_compute_stock_count'
    )

    @api.depends('location_id')
    def _compute_stock_count(self):
        for rec in self:
            if rec.location_id:
                rec.current_stock_count = self.env['stock.quant'].search_count([
                    ('location_id', '=', rec.location_id.id),
                    ('quantity', '>', 0),
                ])
            else:
                rec.current_stock_count = 0

    def _create_stock_location(self, name):
        parent = self.env['stock.location'].search([
            ('usage', '=', 'view'),
            ('name', '=', 'Medical Center'),
        ], limit=1)
        vals = {'name': name, 'usage': 'internal'}
        if parent:
            vals['location_id'] = parent.id
        return self.env['stock.location'].create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('location_id'):
                location = self._create_stock_location(vals['name'])
                vals['location_id'] = location.id
        return super().create(vals_list)

    def write(self, vals):
        if 'name' in vals:
            for rec in self:
                if rec.location_id:
                    rec.location_id.name = vals['name']
        return super().write(vals)

    def action_view_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock in %s') % self.name,
            'res_model': 'stock.quant',
            'view_mode': 'list',
            'domain': [('location_id', '=', self.location_id.id)],
        }
