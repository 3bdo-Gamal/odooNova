from datetime import timedelta

from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
from odoo.osv import expression
import io
import base64


try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class PurchaseBillsDashboard(models.AbstractModel):
    _name = 'wb.purchase.bills.dashboard'
    _description = 'Purchase Bills Dashboard Logic'

    @api.model
    def get_filter_options(self):
        """ جلب البيانات لملء قوائم الفلاتر في الواجهة """
        self.env.cr.execute("""
            SELECT DISTINCT p.id, p.name 
            FROM account_move m 
            JOIN res_partner p ON m.partner_id = p.id 
            WHERE m.move_type = 'in_invoice'
        """)
        vendors = [{'id': row[0], 'name': row[1]} for row in self.env.cr.fetchall()]

        journals = self.env['account.journal'].search_read([('type', 'in', ['purchase', 'bank', 'cash'])],
                                                           ['id', 'name'])

        categories = self.env['product.category'].search_read([], ['id', 'name'])
        locations = self.env['stock.location'].search_read([('usage', '=', 'internal')], ['id', 'display_name'])

        return {
            'vendors': vendors,
            'journals': journals,
            'categories': categories,
            'locations': locations
        }

    @api.model
    def get_dashboard_data(self, period=30, date_from=None, date_to=None, active_filters=None, vendor_id='all',
                           journal_id='all', category_id='all', location_id='all', native_domain=None):
        today = fields.Date.context_today(self)

        base_domain = [('move_type', '=', 'in_invoice')]

        # Fixed dates
        if date_from or date_to:
            if date_from:
                base_domain.append(('invoice_date', '>=', fields.Date.to_date(date_from)))
            if date_to:
                base_domain.append(('invoice_date', '<=', fields.Date.to_date(date_to)))
        # Date Range
        elif period and int(period) > 0:
            current_date_start = today - timedelta(days=int(period))
            base_domain.append(('invoice_date', '>=', current_date_start))
            base_domain.append(('invoice_date', '<=', today))

        # (Sidebar)
        if vendor_id and vendor_id != 'all':
            base_domain.append(('partner_id', '=', int(vendor_id)))

        if journal_id and journal_id != 'all':
            base_domain.append(('journal_id', '=', int(journal_id)))


        if category_id and category_id != 'all':
            base_domain.append(('invoice_line_ids.product_id.categ_id', 'child_of', int(category_id)))

        if location_id and location_id != 'all':
            base_domain.append(
                ('invoice_line_ids.purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of',
                 int(location_id)))

        #  (Quick Filters)
        if active_filters:
            states = []
            if active_filters.get('state_posted'): states.append('posted')
            if active_filters.get('state_draft'): states.append('draft')
            if states:
                base_domain.append(('state', 'in', states))
            else:
                base_domain.append(('state', '=', 'posted'))

            payments = []
            if active_filters.get('pay_paid'): payments.append('paid')
            if active_filters.get('pay_not_paid'): payments.extend(['not_paid', 'partial'])
            if payments:
                base_domain.append(('payment_state', 'in', payments))

            if active_filters.get('is_overdue'):
                base_domain.append(('invoice_date_due', '<', today))
                base_domain.append(('payment_state', 'in', ['not_paid', 'partial']))

            if active_filters.get('has_po'):
                base_domain.append(('purchase_id', '!=', False))
            if active_filters.get('no_po'):
                base_domain.append(('purchase_id', '=', False))

        # (Native Search Bar)
        if native_domain:
            domain = expression.AND([base_domain, native_domain])
        else:
            domain = base_domain

        bills = self.env['account.move'].search(domain)

        # =========================================================
        # 2. KPIs Calculation (حساب الكروت العلوية)
        # =========================================================

        total_bills_count = len(bills)
        total_bills_amount = sum(bills.mapped('amount_total'))

        upcoming_payables = sum(bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'] and b.invoice_date_due and b.invoice_date_due >= today).mapped('amount_residual'))

        dpo_list = bills.filtered(lambda b: b.payment_lead_time > 0).mapped('payment_lead_time')
        avg_dpo = round(sum(dpo_list) / len(dpo_list)) if dpo_list else 0

        unpaid_bills = bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])
        late_bills = unpaid_bills.filtered(lambda b: b.overdue_days > 0)
        late_bills_ratio = round((len(late_bills) / len(unpaid_bills)) * 100) if unpaid_bills else 0

        bills_without_po = bills.filtered(lambda b: not b.purchase_id)
        wo_po_ratio = round((len(bills_without_po) / len(bills)) * 100) if bills else 0

        paid_amount = sum(bills.filtered(lambda b: b.payment_state == 'paid').mapped('amount_total'))
        unpaid_total = sum(unpaid_bills.mapped('amount_residual'))

        # =========================================================
        # 3. Invoice Accuracy & Variances (الكميات والأسعار)
        # =========================================================
        bill_lines = self.env['account.move.line'].search([
            ('move_id', 'in', bills.ids),
            ('purchase_line_id', '!=', False),
            ('product_id', '!=', False)
        ])

        qty_pivot = []
        product_variances = {}
        overbilled_data = {}
        underbilled_data = {}

        for line in bill_lines:
            prod_name = line.product_id.name
            if line.qty_variance != 0:
                product_variances[prod_name] = product_variances.get(prod_name, 0) + line.qty_variance

            if line.price_variance > 0:
                overbilled_data[prod_name] = overbilled_data.get(prod_name, 0) + line.price_variance
            elif line.price_variance < 0:
                underbilled_data[prod_name] = underbilled_data.get(prod_name, 0) + abs(line.price_variance)

        for p, v in product_variances.items():
            qty_pivot.append({'product': p, 'qty_variance': round(v, 2)})

        qty_pivot = sorted(qty_pivot, key=lambda k: abs(k['qty_variance']), reverse=True)[:10]

        variance_products = list(set(list(overbilled_data.keys()) + list(underbilled_data.keys())))[:10]
        overbilled_arr = [round(overbilled_data.get(p, 0), 2) for p in variance_products]
        underbilled_arr = [round(underbilled_data.get(p, 0), 2) for p in variance_products]

        # =========================================================
        # 4. Standard Charts Queries
        # =========================================================
        trend_data = self.env['account.move'].read_group(domain, ['invoice_date', 'amount_total'], ['invoice_date:month'])
        trend_labels = [d['invoice_date:month'] for d in trend_data]
        trend_values = [d['amount_total'] for d in trend_data]

        vendor_data = self.env['account.move'].read_group(domain, ['partner_id', 'amount_total'], ['partner_id'], limit=10, orderby='amount_total desc')
        vendor_labels = [d['partner_id'][1] if d['partner_id'] else 'Unknown' for d in vendor_data]
        vendor_values = [d['amount_total'] for d in vendor_data]

        lead_data = self.env['account.move'].read_group(domain, ['partner_id', 'payment_lead_time'], ['partner_id'], limit=5)
        lead_labels = [d['partner_id'][1] if d['partner_id'] else 'Unknown' for d in lead_data]
        lead_values = [d['payment_lead_time'] for d in lead_data]

        return {
            'cards': {
                'total_bills_count': total_bills_count,
                'total_bills_amount': f"${total_bills_amount:,.0f}",
                'upcoming_payables': f"${upcoming_payables:,.0f}",
                'avg_dpo': avg_dpo,
                'late_bills_ratio': late_bills_ratio,
                'wo_po_ratio': wo_po_ratio,
            },
            'tables': {
                'qty_variance_pivot': qty_pivot
            },
            'charts': {
                'status': {
                    'labels': ['Paid', 'Unpaid'],
                    'datasets': [{'data': [paid_amount, unpaid_total], 'backgroundColor': ['#2ECC71', '#E74C3C']}]
                },
                'trend': {
                    'labels': trend_labels,
                    'datasets': [{'label': 'Total Spend', 'data': trend_values, 'borderColor': '#3498DB', 'fill': False}]
                },
                'vendor': {
                    'labels': vendor_labels,
                    'datasets': [{'label': 'Amount', 'data': vendor_values, 'backgroundColor': '#27AE60'}]
                },
                'lead_time': {
                    'labels': lead_labels,
                    'datasets': [{'label': 'Avg Days', 'data': lead_values, 'backgroundColor': '#F39C12'}]
                },
                'price_var': {
                    'labels': variance_products,
                    'datasets': [
                        {'label': 'Overbilled', 'data': overbilled_arr, 'backgroundColor': '#E74C3C'},
                        {'label': 'Underbilled', 'data': underbilled_arr, 'backgroundColor': '#2ECC71'}
                    ]
                }
            }
        }

    @api.model
    def export_bills_excel(self, period=30, date_from=None, date_to=None, vendor_id='all', journal_id='all',
                           category_id='all', location_id='all', active_filters=None, native_domain=None):
        """ إنشاء وتصدير ملف Excel تحليلي ومفصل للفواتير والانحرافات """
        today = fields.Date.context_today(self)

        # 1. بناء الدومين (نفس منطق الداشبورد تماماً)
        base_domain = [('move_type', '=', 'in_invoice')]
        if date_from or date_to:
            if date_from: base_domain.append(('invoice_date', '>=', fields.Date.to_date(date_from)))
            if date_to: base_domain.append(('invoice_date', '<=', fields.Date.to_date(date_to)))
        elif period and int(period) > 0:
            current_date_start = today - timedelta(days=int(period))
            base_domain.append(('invoice_date', '>=', current_date_start))
            base_domain.append(('invoice_date', '<=', today))

        if vendor_id and vendor_id != 'all': base_domain.append(('partner_id', '=', int(vendor_id)))
        if journal_id and journal_id != 'all': base_domain.append(('journal_id', '=', int(journal_id)))
        if category_id and category_id != 'all': base_domain.append(
            ('invoice_line_ids.product_id.categ_id', 'child_of', int(category_id)))
        if location_id and location_id != 'all': base_domain.append(
            ('invoice_line_ids.purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of',
             int(location_id)))

        if active_filters:
            states = []
            if active_filters.get('state_posted'): states.append('posted')
            if active_filters.get('state_draft'): states.append('draft')
            if states:
                base_domain.append(('state', 'in', states))
            else:
                base_domain.append(('state', '=', 'posted'))

            payments = []
            if active_filters.get('pay_paid'): payments.append('paid')
            if active_filters.get('pay_not_paid'): payments.extend(['not_paid', 'partial'])
            if payments: base_domain.append(('payment_state', 'in', payments))

            if active_filters.get('is_overdue'):
                base_domain.append(('invoice_date_due', '<', today))
                base_domain.append(('payment_state', 'in', ['not_paid', 'partial']))

            if active_filters.get('has_po'): base_domain.append(('purchase_id', '!=', False))
            if active_filters.get('no_po'): base_domain.append(('purchase_id', '=', False))

        domain = expression.AND([base_domain, native_domain]) if native_domain else base_domain
        bills = self.env['account.move'].search(domain)

        # 2. حساب الـ KPIs لعرضها في الإكسيل
        total_bills_count = len(bills)
        total_bills_amount = sum(bills.mapped('amount_total'))
        upcoming_payables = sum(bills.filtered(lambda b: b.payment_state in ['not_paid',
                                                                             'partial'] and b.invoice_date_due and b.invoice_date_due >= today).mapped(
            'amount_residual'))
        unpaid_bills = bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])
        late_bills = unpaid_bills.filtered(lambda b: b.overdue_days > 0)
        late_bills_ratio = round((len(late_bills) / len(unpaid_bills)) * 100) if unpaid_bills else 0

        # 3. تجهيز الإكسيل
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # تنسيقات الخلايا
        title_format = workbook.add_format({'bold': True, 'font_size': 16, 'color': '#1e293b'})
        kpi_header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#f8fafc', 'border': 1, 'font_color': '#475569'})
        kpi_value_format = workbook.add_format({'bold': True, 'border': 1, 'color': '#0f172a', 'align': 'center'})
        kpi_money_format = workbook.add_format(
            {'bold': True, 'border': 1, 'color': '#10b981', 'num_format': '#,##0.00', 'align': 'center'})
        kpi_danger_format = workbook.add_format(
            {'bold': True, 'border': 1, 'color': '#ef4444', 'num_format': '#,##0.00', 'align': 'center'})

        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_format = workbook.add_format({'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1, 'align': 'center'})
        warning_format = workbook.add_format({'border': 1, 'align': 'center', 'font_color': '#ef4444', 'bold': True})

        # =================================================================
        # الورقة الأولى (Sheet 1): ملخص الـ KPIs وتفاصيل الفواتير الأساسية
        # =================================================================
        sheet1 = workbook.add_worksheet('Bills Overview')
        sheet1.write('A1', 'Purchase Bills Analytical Report', title_format)

        # رسم جدول الـ KPIs المصغر
        sheet1.write('A3', 'Total Bills Count', kpi_header_format)
        sheet1.write('B3', total_bills_count, kpi_value_format)
        sheet1.write('A4', 'Total Billed Amount', kpi_header_format)
        sheet1.write('B4', total_bills_amount, kpi_money_format)

        sheet1.write('D3', 'Upcoming Payables', kpi_header_format)
        sheet1.write('E3', upcoming_payables, kpi_danger_format)
        sheet1.write('D4', 'Late Bills Ratio', kpi_header_format)
        sheet1.write('E4', f"{late_bills_ratio}%", kpi_value_format)

        # عناوين الفواتير
        headers1 = ['Bill Number', 'Vendor', 'Source PO', 'Bill Date', 'Due Date', 'Total Amount', 'Amount Due',
                    'Lead Time (Days)', 'Overdue Days', 'Status', 'Payment Status']
        for col_num, header in enumerate(headers1):
            sheet1.write(6, col_num, header, header_format)
            sheet1.set_column(col_num, col_num, 18)
        sheet1.set_column(1, 1, 25)  # توسيع خانة المورد

        # كتابة الفواتير
        row = 7
        for bill in bills:
            po_ref = bill.invoice_origin or (bill.purchase_id.name if bill.purchase_id else 'No PO (Maverick)')
            sheet1.write(row, 0, bill.name or 'Draft', text_format)
            sheet1.write(row, 1, bill.partner_id.name or '', text_format)
            sheet1.write(row, 2, po_ref, text_format)
            sheet1.write(row, 3, str(bill.invoice_date or ''), text_format)
            sheet1.write(row, 4, str(bill.invoice_date_due or ''), text_format)
            sheet1.write(row, 5, bill.amount_total, money_format)
            sheet1.write(row, 6, bill.amount_residual, money_format)
            sheet1.write(row, 7, bill.payment_lead_time, num_format)

            # تلوين أيام التأخير بالأحمر إذا كانت أكبر من صفر
            sheet1.write(row, 8, bill.overdue_days, warning_format if bill.overdue_days > 0 else num_format)

            state_label = dict(bill._fields['state'].selection).get(bill.state, '')
            payment_label = dict(bill._fields['payment_state'].selection).get(bill.payment_state, '')
            sheet1.write(row, 9, state_label, text_format)
            sheet1.write(row, 10, payment_label, text_format)
            row += 1

        # =================================================================
        # الورقة الثانية (Sheet 2): تفاصيل الانحرافات (Variances)
        # =================================================================
        sheet2 = workbook.add_worksheet('Invoice Line Variances')
        sheet2.write('A1', 'Detailed Product Variances (PO vs Bill)', title_format)
        sheet2.write('A2', 'This sheet shows only the product lines that have a price or quantity mismatch.',
                     workbook.add_format({'italic': True, 'color': '#64748b'}))

        headers2 = ['Bill Number', 'Vendor', 'Product', 'PO Price', 'Bill Price', 'Price Variance', 'PO Qty',
                    'Bill Qty', 'Qty Variance']
        for col_num, header in enumerate(headers2):
            sheet2.write(3, col_num, header, header_format)
            sheet2.set_column(col_num, col_num, 16)
        sheet2.set_column(2, 2, 35)  # توسيع خانة المنتج

        # جلب المنتجات المرتبطة بالفواتير المفلترة ولها أمر شراء
        bill_lines = self.env['account.move.line'].search([
            ('move_id', 'in', bills.ids),
            ('purchase_line_id', '!=', False),
            ('product_id', '!=', False)
        ])

        row2 = 4
        for line in bill_lines:
            # فلترة ذكية: إظهار الخطوط التي فيها انحراف فقط!
            if line.price_variance != 0 or line.qty_variance != 0:
                sheet2.write(row2, 0, line.move_id.name or '', text_format)
                sheet2.write(row2, 1, line.partner_id.name or '', text_format)
                sheet2.write(row2, 2, line.product_id.name or '', text_format)
                sheet2.write(row2, 3, line.purchase_price_unit, money_format)
                sheet2.write(row2, 4, line.price_unit, money_format)

                # تلوين الانحراف بالأحمر إذا كان ضد الشركة (Overbilled)
                sheet2.write(row2, 5, line.price_variance, warning_format if line.price_variance > 0 else money_format)

                sheet2.write(row2, 6, line.purchase_line_id.product_qty, num_format)
                sheet2.write(row2, 7, line.quantity, num_format)

                sheet2.write(row2, 8, line.qty_variance, warning_format if line.qty_variance > 0 else num_format)
                row2 += 1

        workbook.close()
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': f'Purchase_Analytics_{fields.Date.today()}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id

class AccountMove(models.Model):
    _inherit = 'account.move'
    payment_lead_time = fields.Integer(compute='_compute_payment_lead_time', string='Lead Time (Days)', store=True)
    overdue_days = fields.Integer(compute='_compute_overdue_days', string='Overdue Days')

    @api.depends('invoice_date', 'invoice_date_due')
    def _compute_payment_lead_time(self):
        for move in self:
            if move.invoice_date and move.invoice_date_due:
                move.payment_lead_time = (move.invoice_date_due - move.invoice_date).days
            else:
                move.payment_lead_time = 0

    def _compute_overdue_days(self):
        today = fields.Date.context_today(self)
        for move in self:
            if move.state == 'posted' and move.payment_state in ('not_paid', 'partial') and move.invoice_date_due and move.invoice_date_due < today:
                move.overdue_days = (today - move.invoice_date_due).days
            else:
                move.overdue_days = 0

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    purchase_price_unit = fields.Float(related='purchase_line_id.price_unit', string='PO Price', readonly=True)
    price_variance = fields.Float(compute='_compute_variances', string='Price Variance', store=True)
    qty_variance = fields.Float(compute='_compute_variances', string='Qty Variance', store=True)

    @api.depends('price_unit', 'purchase_price_unit', 'quantity', 'purchase_line_id.product_qty')
    def _compute_variances(self):
        for line in self:
            if line.purchase_line_id and line.move_id.move_type == 'in_invoice':
                line.price_variance = line.price_unit - line.purchase_price_unit
                line.qty_variance = line.quantity - line.purchase_line_id.product_qty
            else:
                line.price_variance = 0.0
                line.qty_variance = 0.0