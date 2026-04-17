from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta
import io
import base64


class MedicalAnalyticsReport(models.TransientModel):
    _name = 'medical.analytics.report'
    _description = 'Medical Inventory Analytics Report Wizard'

    report_type = fields.Selection([
        ('purchase', 'Purchase Report'),
        ('consumption', 'Consumption Report'),
        ('stock', 'Current Stock Report'),
        ('expiry', 'Expiry Report'),
    ], string='Report Type', required=True, default='purchase')

    date_from = fields.Date(string='Date From',
                            default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(string='Date To', default=lambda self: date.today())
    location_id = fields.Many2one('stock.location', string='Location (optional)',
                                  domain=[('usage', '=', 'internal')])
    product_id = fields.Many2one('product.product', string='Product (optional)')
    export_format = fields.Selection([
        ('xlsx', 'Excel (.xlsx)'),
        ('pdf', 'PDF'),
    ], string='Format', required=True, default='xlsx')

    file_data = fields.Binary(string='Download', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')],
                             default='draft')

    def action_generate(self):
        self.ensure_one()
        if self.export_format == 'xlsx':
            self._generate_xlsx()
        else:
            self._generate_pdf()
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'medical.analytics.report',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _get_purchase_data(self):
        domain = [('receive_id.state', '=', 'done')]
        if self.date_from:
            domain.append(('receive_id.date_receive', '>=', str(self.date_from)))
        if self.date_to:
            domain.append(('receive_id.date_receive', '<=', str(self.date_to) + ' 23:59:59'))
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.location_id:
            domain.append(('receive_id.destination_location_id', '=', self.location_id.id))
        lines = self.env['medical.stock.receive.line'].search(domain)
        rows = []
        for l in lines:
            rows.append({
                'Date': l.receive_id.date_receive.strftime('%Y-%m-%d') if l.receive_id.date_receive else '',
                'Receipt': l.receive_id.name,
                'Vendor': l.receive_id.vendor_id.name or l.receive_id.vendor_name or '',
                'Location': l.receive_id.destination_location_id.name or '',
                'Product': l.product_id.name,
                'Quantity': l.quantity,
                'Unit': l.product_uom_id.name or '',
                'Unit Price': l.unit_price,
                'Total': l.subtotal,
                'Expiry Date': l.expiry_date.strftime('%Y-%m-%d') if l.expiry_date else '',
            })
        return rows

    def _get_consumption_data(self):
        domain = [
            ('request_id.state', '=', 'done'),
            ('request_id.request_type', '=', 'consumption'),
        ]
        if self.date_from:
            domain.append(('date_request', '>=', str(self.date_from)))
        if self.date_to:
            domain.append(('date_request', '<=', str(self.date_to) + ' 23:59:59'))
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.location_id:
            domain.append(('department_location_id', '=', self.location_id.id))
        lines = self.env['medical.consumption.request.line'].search(domain)
        rows = []
        for l in lines:
            rows.append({
                'Date': l.date_request.strftime('%Y-%m-%d') if l.date_request else '',
                'Request': l.request_id.name,
                'Clinic': l.department_location_id.name or '',
                'Requested By': l.request_id.requested_by.name or '',
                'Product': l.product_id.name,
                'Quantity': l.quantity,
                'Unit': l.product_uom_id.name or '',
            })
        return rows

    def _get_stock_data(self):
        domain = [('location_id.usage', '=', 'internal'), ('quantity', '>', 0)]
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        quants = self.env['stock.quant'].search(domain)
        rows = []
        for q in quants:
            rows.append({
                'Location': q.location_id.name or '',
                'Product': q.product_id.name,
                'Category': q.product_id.categ_id.name or '',
                'Quantity': q.quantity,
                'Unit': q.product_id.uom_id.name or '',
                'Cost Price': q.product_id.standard_price,
                'Total Value': round(q.quantity * q.product_id.standard_price, 2),
            })
        return rows

    def _get_expiry_data(self):
        domain = [('expiry_date', '!=', False), ('receive_id.state', '=', 'done')]
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        lines = self.env['medical.stock.receive.line'].search(domain, order='expiry_date asc')
        today = date.today()
        rows = []
        for l in lines:
            exp = l.expiry_date.date() if l.expiry_date else None
            days = (exp - today).days if exp else None
            status = 'Expired' if days is not None and days < 0 else \
                     'Critical (≤5 days)' if days is not None and days <= 5 else \
                     'Warning (≤30 days)' if days is not None and days <= 30 else 'OK'
            rows.append({
                'Product': l.product_id.name,
                'Quantity': l.quantity,
                'Unit': l.product_uom_id.name or '',
                'Expiry Date': l.expiry_date.strftime('%Y-%m-%d') if l.expiry_date else '',
                'Days Left': days if days is not None else '',
                'Status': status,
                'Location': l.receive_id.destination_location_id.name or '',
                'Receipt': l.receive_id.name,
            })
        return rows

    def _generate_xlsx(self):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter is not installed. Please install it on the server.'))

        report_map = {
            'purchase': ('Purchase Report', self._get_purchase_data),
            'consumption': ('Consumption Report', self._get_consumption_data),
            'stock': ('Current Stock Report', self._get_stock_data),
            'expiry': ('Expiry Report', self._get_expiry_data),
        }
        title, data_fn = report_map[self.report_type]
        rows = data_fn()

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output)
        ws = wb.add_worksheet(title[:31])

        # Formats
        hdr_fmt = wb.add_format({
            'bold': True, 'bg_color': '#1565c0', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        money_fmt = wb.add_format({'num_format': '#,##0.00', 'border': 1})
        num_fmt = wb.add_format({'num_format': '#,##0.##', 'border': 1})
        cell_fmt = wb.add_format({'border': 1})
        red_fmt = wb.add_format({'bg_color': '#FFCCCC', 'border': 1})
        orange_fmt = wb.add_format({'bg_color': '#FFE0B2', 'border': 1})

        # Title row
        ws.merge_range(0, 0, 0, max(len(rows[0].keys()) - 1 if rows else 3, 3),
                       f'Medical Inventory - {title}', wb.add_format({
                           'bold': True, 'font_size': 14, 'align': 'center',
                           'bg_color': '#0d47a1', 'font_color': 'white',
                       }))
        ws.merge_range(1, 0, 1, max(len(rows[0].keys()) - 1 if rows else 3, 3),
                       f'Period: {self.date_from or "All"} to {self.date_to or "All"}',
                       wb.add_format({'italic': True, 'align': 'center', 'bg_color': '#e3f2fd'}))

        if not rows:
            ws.write(3, 0, 'No data found for the selected filters.')
            wb.close()
            self.file_data = base64.b64encode(output.getvalue())
            self.file_name = f'{self.report_type}_report.xlsx'
            return

        headers = list(rows[0].keys())
        for col, h in enumerate(headers):
            ws.write(3, col, h, hdr_fmt)
            ws.set_column(col, col, max(15, len(h) + 4))

        money_cols = {'Unit Price', 'Total', 'Total Value', 'Cost Price'}
        num_cols = {'Quantity', 'Days Left'}

        for row_i, row in enumerate(rows):
            row_fmt = cell_fmt
            if self.report_type == 'expiry':
                status = row.get('Status', '')
                if 'Expired' in status:
                    row_fmt = red_fmt
                elif 'Critical' in status:
                    row_fmt = orange_fmt
            for col, h in enumerate(headers):
                val = row.get(h, '')
                if h in money_cols and val != '':
                    ws.write_number(row_i + 4, col, float(val or 0), money_fmt)
                elif h in num_cols and val != '':
                    ws.write_number(row_i + 4, col, float(val or 0), num_fmt)
                else:
                    ws.write(row_i + 4, col, str(val) if val != '' else '', row_fmt)

        # Summary row
        summary_row = len(rows) + 5
        ws.write(summary_row, 0, f'Total Records: {len(rows)}',
                 wb.add_format({'bold': True, 'bg_color': '#f5f5f5'}))
        if self.report_type == 'purchase':
            total_spend = sum(r.get('Total', 0) for r in rows)
            ws.write(summary_row, len(headers) - 1,
                     total_spend, wb.add_format({'bold': True, 'num_format': '#,##0.00', 'bg_color': '#e8f5e9'}))
        if self.report_type == 'stock':
            total_val = sum(r.get('Total Value', 0) for r in rows)
            ws.write(summary_row, len(headers) - 1,
                     total_val, wb.add_format({'bold': True, 'num_format': '#,##0.00', 'bg_color': '#e8f5e9'}))

        wb.close()
        self.file_data = base64.b64encode(output.getvalue())
        self.file_name = f'medical_{self.report_type}_report_{date.today()}.xlsx'

    def _generate_pdf(self):
        """Generate PDF using ReportLab (pure Python, no wkhtmltopdf needed)."""
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.units import cm
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
        except ImportError:
            raise UserError(_(
                'ReportLab is not installed. Please run this command on your server:\n'
                'pip install reportlab --break-system-packages\n\n'
                'Or use Excel export instead which works without any extra installation.'
            ))

        report_map = {
            'purchase': ('Purchase Report', self._get_purchase_data),
            'consumption': ('Consumption Report', self._get_consumption_data),
            'stock': ('Current Stock Report', self._get_stock_data),
            'expiry': ('Expiry Report', self._get_expiry_data),
        }
        title, data_fn = report_map[self.report_type]
        rows = data_fn()

        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4),
                                leftMargin=1*cm, rightMargin=1*cm,
                                topMargin=1.5*cm, bottomMargin=1.5*cm)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle('title', parent=styles['Heading1'],
                                     textColor=colors.HexColor('#1565c0'),
                                     fontSize=16, spaceAfter=4)
        story.append(Paragraph(f'Medical Inventory — {title}', title_style))

        sub_style = ParagraphStyle('sub', parent=styles['Normal'],
                                   textColor=colors.HexColor('#666666'), fontSize=10)
        period = f'{self.date_from or "All"} to {self.date_to or "All"}'
        story.append(Paragraph(f'Period: {period} | Generated: {date.today()}', sub_style))
        story.append(Spacer(1, 0.4*cm))

        if not rows:
            story.append(Paragraph('No data found for the selected filters.', styles['Normal']))
        else:
            headers = list(rows[0].keys())
            table_data = [headers]
            for row in rows:
                table_data.append([str(row.get(h, '') or '') for h in headers])

            col_width = (landscape(A4)[0] - 2*cm) / len(headers)
            col_widths = [col_width] * len(headers)

            t = Table(table_data, colWidths=col_widths, repeatRows=1)
            ts = TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1565c0')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 9),
                ('ALIGN', (0,0), (-1,0), 'CENTER'),
                ('FONTSIZE', (0,1), (-1,-1), 8),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f5f5f5')]),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ])
            # Highlight expiry rows
            if self.report_type == 'expiry':
                for i, row in enumerate(rows, start=1):
                    status = row.get('Status', '')
                    if 'Expired' in status:
                        ts.add('BACKGROUND', (0,i), (-1,i), colors.HexColor('#ffcccc'))
                    elif 'Critical' in status:
                        ts.add('BACKGROUND', (0,i), (-1,i), colors.HexColor('#ffe0b2'))
            t.setStyle(ts)
            story.append(t)
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph(f'Total Records: {len(rows)}',
                                   ParagraphStyle('footer', parent=styles['Normal'],
                                                  textColor=colors.HexColor('#1565c0'),
                                                  fontName='Helvetica-Bold', fontSize=9)))

        doc.build(story)
        self.file_data = base64.b64encode(output.getvalue())
        self.file_name = f'medical_{self.report_type}_report_{date.today()}.pdf'
