from odoo import http
from odoo.http import request
from datetime import date, timedelta


class MedicalInventoryDashboard(http.Controller):

    @http.route('/medical_inventory/dashboard_data', type='json', auth='user')
    def dashboard_data(self):
        env = request.env
        today = date.today()
        in_5 = today + timedelta(days=5)
        in_30 = today + timedelta(days=30)

        # Stock summary
        quants = env['stock.quant'].sudo().search([
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ])
        total_products = len(set(quants.mapped('product_id').ids))
        total_qty = sum(quants.mapped('quantity'))
        total_value = sum(q.quantity * (q.product_id.standard_price or 0) for q in quants)

        # Requests
        pending = env['medical.consumption.request'].sudo().search_count([('state', '=', 'submitted')])
        approved = env['medical.consumption.request'].sudo().search_count([('state', '=', 'approved')])

        # Expiry - only within 5 days and expired
        expired_lines = env['medical.stock.receive.line'].sudo().search([
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', str(today)),
            ('receive_id.state', '=', 'done'),
        ])
        critical_lines = env['medical.stock.receive.line'].sudo().search([
            ('expiry_date', '!=', False),
            ('expiry_date', '>', str(today)),
            ('expiry_date', '<=', str(in_5)),
            ('receive_id.state', '=', 'done'),
        ])

        # Recent receipts
        receipts = env['medical.stock.receive'].sudo().search(
            [('state', '=', 'done')], order='date_receive desc', limit=5)
        receipts_data = [{
            'name': r.name,
            'date': r.date_receive.strftime('%d %b %Y') if r.date_receive else '',
            'vendor': r.vendor_id.name or r.vendor_name or 'Unknown',
            'location': r.destination_location_id.name or '',
            'value': round(r.total_value, 2),
        } for r in receipts]

        # Stock per location
        locations = env['stock.location'].sudo().search([
            ('usage', '=', 'internal'), ('active', '=', True)
        ])
        loc_data = []
        for loc in locations:
            lq = env['stock.quant'].sudo().search([
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

        # Expiry items - expired + expiring in 5 days only
        expiry_items = []
        for l in list(expired_lines) + list(critical_lines):
            days = (l.expiry_date.date() - today).days if l.expiry_date else 0
            expiry_items.append({
                'product': l.product_id.name,
                'qty': l.quantity,
                'expiry': l.expiry_date.strftime('%d %b %Y') if l.expiry_date else '',
                'days_left': days,
                'location': l.receive_id.destination_location_id.name or '',
                'expired': days < 0,
                'critical': 0 <= days <= 5,
            })
        expiry_items.sort(key=lambda x: x['days_left'])

        # Analytics: monthly spend last 6 months
        from dateutil.relativedelta import relativedelta
        monthly_spend = []
        for i in range(5, -1, -1):
            month_start = (today.replace(day=1) - relativedelta(months=i))
            month_end = (month_start + relativedelta(months=1))
            month_receipts = env['medical.stock.receive'].sudo().search([
                ('state', '=', 'done'),
                ('date_receive', '>=', str(month_start)),
                ('date_receive', '<', str(month_end)),
            ])
            total = round(sum(r.total_value for r in month_receipts), 2)
            monthly_spend.append({
                'month': month_start.strftime('%b %Y'),
                'value': total,
                'count': len(month_receipts),
            })

        # Top products by total received value
        all_lines = env['medical.stock.receive.line'].sudo().search([
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
            'expired_count': len(expired_lines),
            'critical_count': len(critical_lines),
            'recent_receipts': receipts_data,
            'locations': loc_data[:10],
            'expiry_items': expiry_items,
            'monthly_spend': monthly_spend,
            'top_products': top_products,
        }
