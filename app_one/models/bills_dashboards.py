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

    # =========================================================
    # 1. Fetch Sidebar Options
    # =========================================================
    @api.model
    def get_filter_options(self):
        """ جلب البيانات لملء قوائم الفلاتر بناءً على الاستخدام الفعلي في المشتريات """

        # 1. جلب الموردين الذين لديهم فواتير مشتريات فعلاً
        self.env.cr.execute("""
                            SELECT DISTINCT partner_id
                            FROM account_move
                            WHERE move_type = 'in_invoice'
                              AND partner_id IS NOT NULL
                            """)
        vendor_ids = [row[0] for row in self.env.cr.fetchall()]
        vendors = self.env['res.partner'].search_read([('id', 'in', vendor_ids)], ['id', 'name'])

        # 2. جلب اليوميات (حل مشكلة object Object)
        self.env.cr.execute("""
                            SELECT DISTINCT journal_id
                            FROM account_move
                            WHERE move_type = 'in_invoice'
                              AND journal_id IS NOT NULL
                            """)
        journal_ids = [row[0] for row in self.env.cr.fetchall()]
        journals = self.env['account.journal'].search_read([('id', 'in', journal_ids)], ['id', 'name'])

        # 3. جلب شروط الدفع (حل مشكلة object Object)
        self.env.cr.execute("""
                            SELECT DISTINCT invoice_payment_term_id
                            FROM account_move
                            WHERE move_type = 'in_invoice'
                              AND invoice_payment_term_id IS NOT NULL
                            """)
        term_ids = [row[0] for row in self.env.cr.fetchall()]
        payment_terms = self.env['account.payment.term'].search_read([('id', 'in', term_ids)], ['id', 'name'])

        categories = self.env['product.category'].search_read([], ['id', 'name'])
        locations = self.env['stock.location'].search_read([('usage', '=', 'internal')], ['id', 'display_name'])

        return {
            'vendors': vendors,
            'journals': journals,
            'payment_terms': payment_terms,
            'categories': categories,
            'locations': locations
        }

    # =========================================================
    # Helper Method: Build Domain
    # =========================================================
    def _build_combined_domain(self, kwargs):
        """ تدمج فلاتر الشريط الجانبي مع شريط بحث أودو الأساسي """
        today = fields.Date.context_today(self)
        base_domain = [('move_type', '=', 'in_invoice')]

        period = kwargs.get('period', 0)
        date_from = kwargs.get('date_from')
        date_to = kwargs.get('date_to')
        vendor_id = kwargs.get('vendor_id', 'all')
        journal_id = kwargs.get('journal_id', 'all')
        payment_term_id = kwargs.get('payment_term_id', 'all')
        category_id = kwargs.get('category_id', 'all')
        location_id = kwargs.get('location_id', 'all')
        active_filters = kwargs.get('active_filters', {})
        native_domain = kwargs.get('native_domain', [])

        # 1. Date Filters
        if date_from or date_to:
            if date_from: base_domain.append(('invoice_date', '>=', fields.Date.to_date(date_from)))
            if date_to: base_domain.append(('invoice_date', '<=', fields.Date.to_date(date_to)))
        elif period and int(period) > 0:
            current_date_start = today - timedelta(days=int(period))
            base_domain.append(('invoice_date', '>=', current_date_start))
            base_domain.append(('invoice_date', '<=', today))

        # 2. Sidebar Dropdown Filters
        if payment_term_id and payment_term_id != 'all':
            base_domain.append(('invoice_payment_term_id', '=', int(payment_term_id)))
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

        # 3. Sidebar Quick Filters (Toggles)
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

            # Fixed PO logic
            if active_filters.get('has_po'): base_domain.append(('invoice_line_ids.purchase_line_id', '!=', False))
            if active_filters.get('no_po'): base_domain.append(('invoice_line_ids.purchase_line_id', '=', False))

        # 4. Merge with Native Search Bar Domain
        if native_domain:
            return expression.AND([base_domain, native_domain])
        return base_domain
    # =========================================================
    # 2. Get Dashboard Data
    # =========================================================
    @api.model
    def get_dashboard_data(self, **kwargs):
        """ Fetch data combining Sidebar Filters + Native Search Bar """
        today = fields.Date.context_today(self)

        # Build unified domain
        domain = self._build_combined_domain(kwargs)

        # Fetch records
        bills = self.env['account.move'].search(domain)

        # KPIs Calculation
        total_bills_count = len(bills)
        total_bills_amount = sum(bills.mapped('amount_total'))

        upcoming_payables = sum(bills.filtered(lambda b: b.payment_state in ['not_paid',
                                                                             'partial'] and b.invoice_date_due and b.invoice_date_due >= today).mapped(
            'amount_residual'))

        dpo_list = bills.filtered(lambda b: b.payment_lead_time > 0).mapped('payment_lead_time')
        avg_dpo = round(sum(dpo_list) / len(dpo_list)) if dpo_list else 0

        unpaid_bills = bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])
        late_bills = unpaid_bills.filtered(lambda b: b.overdue_days > 0)
        late_bills_ratio = round((len(late_bills) / len(unpaid_bills)) * 100) if unpaid_bills else 0

        bills_without_po = bills.filtered(lambda b: not b.invoice_line_ids.mapped('purchase_line_id'))
        wo_po_ratio = round((len(bills_without_po) / len(bills)) * 100) if bills else 0

        paid_amount = sum(bills.filtered(lambda b: b.payment_state == 'paid').mapped('amount_total'))
        unpaid_total = sum(unpaid_bills.mapped('amount_residual'))

        # Variances
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

        # Standard Charts Queries
        trend_data = self.env['account.move'].read_group(domain, ['invoice_date', 'amount_total'],
                                                         ['invoice_date:month'])
        trend_labels = [d['invoice_date:month'] for d in trend_data]
        trend_values = [d['amount_total'] for d in trend_data]

        vendor_data = self.env['account.move'].read_group(domain, ['partner_id', 'amount_total'], ['partner_id'],
                                                          limit=10, orderby='amount_total desc')
        vendor_labels = [d['partner_id'][1] if d['partner_id'] else 'Unknown' for d in vendor_data]
        vendor_values = [d['amount_total'] for d in vendor_data]

        lead_data = self.env['account.move'].read_group(domain, ['partner_id', 'payment_lead_time'], ['partner_id'],
                                                        limit=5)
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
                    'datasets': [
                        {'label': 'Total Spend', 'data': trend_values, 'borderColor': '#3498DB', 'fill': False}]
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

    # =========================================================
    # 3. Export Excel Data
    # =========================================================
    @api.model
    def export_bills_excel(self, **kwargs):
        """ إنشاء وتصدير ملف Excel تحليلي مع الفلاتر الجديدة """
        domain = self._build_combined_domain(kwargs)
        bills = self.env['account.move'].search(domain)
        today = fields.Date.context_today(self)

        # حساب الـ KPIs لعرضها في الإكسيل
        total_bills_count = len(bills)
        total_bills_amount = sum(bills.mapped('amount_total'))
        upcoming_payables = sum(bills.filtered(lambda b: b.payment_state in ['not_paid',
                                                                             'partial'] and b.invoice_date_due and b.invoice_date_due >= today).mapped(
            'amount_residual'))
        unpaid_bills = bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])
        late_bills = unpaid_bills.filtered(lambda b: b.overdue_days > 0)
        late_bills_ratio = round((len(late_bills) / len(unpaid_bills)) * 100) if unpaid_bills else 0

        # تجهيز الإكسيل
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # تنسيقات الخلايا
        title_format = workbook.add_format({'bold': True, 'font_size': 16, 'color': '#1e293b'})
        info_format = workbook.add_format({'italic': True, 'color': '#64748b', 'font_size': 10})
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

        # ==================== Sheet 1 ====================
        sheet1 = workbook.add_worksheet('Bills Overview')
        sheet1.write('A1', 'Purchase Bills Analytical Report', title_format)

        # إضافة سطر معلومات يوضح الفلاتر المطبقة
        journal_id = kwargs.get('journal_id', 'all')
        term_id = kwargs.get('payment_term_id', 'all')
        journal_name = self.env['account.journal'].browse(int(journal_id)).name if journal_id != 'all' else 'All'
        term_name = self.env['account.payment.term'].browse(int(term_id)).name if term_id != 'all' else 'All'
        sheet1.write('A2', f"Filtered By -> Journal: {journal_name} | Payment Term: {term_name}", info_format)

        sheet1.write('A4', 'Total Bills Count', kpi_header_format)
        sheet1.write('B4', total_bills_count, kpi_value_format)
        sheet1.write('A5', 'Total Billed Amount', kpi_header_format)
        sheet1.write('B5', total_bills_amount, kpi_money_format)

        sheet1.write('D4', 'Upcoming Payables', kpi_header_format)
        sheet1.write('E4', upcoming_payables, kpi_danger_format)
        sheet1.write('D5', 'Late Bills Ratio', kpi_header_format)
        sheet1.write('E5', f"{late_bills_ratio}%", kpi_value_format)

        headers1 = ['Bill Number', 'Vendor', 'Source PO', 'Bill Date', 'Due Date', 'Total Amount', 'Amount Due',
                    'Lead Time (Days)', 'Overdue Days', 'Status', 'Payment Status']
        for col_num, header in enumerate(headers1):
            sheet1.write(7, col_num, header, header_format)
            sheet1.set_column(col_num, col_num, 18)
        sheet1.set_column(1, 1, 25)

        row = 8
        for bill in bills:
            # استخراج أسماء أوامر الشراء بشكل آمن
            po_names = ", ".join(set(bill.invoice_line_ids.mapped('purchase_line_id.order_id.name')))
            po_ref = bill.invoice_origin or (po_names if po_names else 'No PO (Maverick)')

            sheet1.write(row, 0, bill.name or 'Draft', text_format)
            sheet1.write(row, 1, bill.partner_id.name or '', text_format)
            sheet1.write(row, 2, po_ref, text_format)
            sheet1.write(row, 3, str(bill.invoice_date or ''), text_format)
            sheet1.write(row, 4, str(bill.invoice_date_due or ''), text_format)
            sheet1.write(row, 5, bill.amount_total, money_format)
            sheet1.write(row, 6, bill.amount_residual, money_format)
            sheet1.write(row, 7, bill.payment_lead_time, num_format)
            sheet1.write(row, 8, bill.overdue_days, warning_format if bill.overdue_days > 0 else num_format)

            state_label = dict(bill._fields['state'].selection).get(bill.state, '')
            payment_label = dict(bill._fields['payment_state'].selection).get(bill.payment_state, '')
            sheet1.write(row, 9, state_label, text_format)
            sheet1.write(row, 10, payment_label, text_format)
            row += 1

        # ==================== Sheet 2 ====================
        sheet2 = workbook.add_worksheet('Invoice Line Variances')
        sheet2.write('A1', 'Detailed Product Variances (PO vs Bill)', title_format)
        sheet2.write('A2', 'This sheet shows only the product lines that have a price or quantity mismatch.',
                     workbook.add_format({'italic': True, 'color': '#64748b'}))

        headers2 = ['Bill Number', 'Vendor', 'Product', 'PO Price', 'Bill Price', 'Price Variance', 'PO Qty',
                    'Bill Qty', 'Qty Variance']
        for col_num, header in enumerate(headers2):
            sheet2.write(3, col_num, header, header_format)
            sheet2.set_column(col_num, col_num, 16)
        sheet2.set_column(2, 2, 35)

        bill_lines = self.env['account.move.line'].search([
            ('move_id', 'in', bills.ids),
            ('purchase_line_id', '!=', False),
            ('product_id', '!=', False)
        ])

        row2 = 4
        for line in bill_lines:
            if line.price_variance != 0 or line.qty_variance != 0:
                sheet2.write(row2, 0, line.move_id.name or '', text_format)
                sheet2.write(row2, 1, line.partner_id.name or '', text_format)
                sheet2.write(row2, 2, line.product_id.name or '', text_format)
                sheet2.write(row2, 3, line.purchase_price_unit, money_format)
                sheet2.write(row2, 4, line.price_unit, money_format)
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


# =========================================================
# Inherits
# =========================================================
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
            if move.state == 'posted' and move.payment_state in ('not_paid',
                                                                 'partial') and move.invoice_date_due and move.invoice_date_due < today:
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