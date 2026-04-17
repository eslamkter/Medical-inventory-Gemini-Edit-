from odoo import http
from odoo.http import request


class MedicalStockView(http.Controller):

    @http.route('/medical_inventory/stock_data', type='json', auth='user')
    def stock_data(self):
        env = request.env

        # All internal locations
        locations = env['stock.location'].sudo().search([
            ('usage', '=', 'internal'), ('active', '=', True)
        ], order='complete_name')

        loc_data = []
        for loc in locations:
            quants = env['stock.quant'].sudo().search([
                ('location_id', '=', loc.id), ('quantity', '>', 0)
            ])
            products = []
            for q in quants:
                products.append({
                    'id': q.product_id.id,
                    'name': q.product_id.name,
                    'category': q.product_id.categ_id.name or '',
                    'qty': round(q.quantity, 2),
                    'unit': q.product_id.uom_id.name or '',
                    'cost': round(q.product_id.standard_price or 0, 2),
                    'value': round(q.quantity * (q.product_id.standard_price or 0), 2),
                    'ref': q.product_id.default_code or '',
                })
            products.sort(key=lambda x: x['name'])
            total_qty = sum(p['qty'] for p in products)
            total_val = sum(p['value'] for p in products)
            loc_data.append({
                'id': loc.id,
                'name': loc.name,
                'full_name': loc.complete_name,
                'products': products,
                'product_count': len(products),
                'total_qty': round(total_qty, 1),
                'total_value': round(total_val, 2),
            })

        # Summary stats
        all_quants = env['stock.quant'].sudo().search([
            ('location_id.usage', '=', 'internal'), ('quantity', '>', 0)
        ])
        total_products = len(set(all_quants.mapped('product_id').ids))
        total_qty = round(sum(all_quants.mapped('quantity')), 1)
        total_value = round(sum(q.quantity * (q.product_id.standard_price or 0) for q in all_quants), 2)

        # Categories breakdown
        cat_map = {}
        for q in all_quants:
            cat = q.product_id.categ_id.name or 'Uncategorized'
            if cat not in cat_map:
                cat_map[cat] = {'name': cat, 'qty': 0, 'value': 0, 'count': 0}
            cat_map[cat]['qty'] += q.quantity
            cat_map[cat]['value'] += q.quantity * (q.product_id.standard_price or 0)
            cat_map[cat]['count'] += 1
        categories = sorted(cat_map.values(), key=lambda x: x['value'], reverse=True)
        for c in categories:
            c['qty'] = round(c['qty'], 1)
            c['value'] = round(c['value'], 2)

        return {
            'locations': loc_data,
            'total_products': total_products,
            'total_qty': total_qty,
            'total_value': total_value,
            'categories': categories,
        }
