from odoo import models, fields, api
from datetime import timedelta
from odoo.osv import expression
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


# =============================================================================
# DASHBOARD LOGIC — Abstract model
# =============================================================================
class PurchaseBillsDashboard(models.AbstractModel):
    _name = 'wb.purchase.bills.dashboard'
    _description = 'Purchase Bills Dashboard Logic'

    # =========================================================================
    # SECTION 1: Filter Options for the Sidebar
    # =========================================================================
    @api.model
    def get_filter_options(self):
        # Vendors (Safely filtering None values)
        self.env.cr.execute("""
                            SELECT DISTINCT partner_id
                            FROM account_move
                            WHERE move_type = 'in_invoice'
                              AND partner_id IS NOT NULL
                            """)
        vendor_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        vendors = self.env['res.partner'].search_read(
            [('id', 'in', vendor_ids)], ['id', 'name']
        )

        # Journals
        self.env.cr.execute("""
                            SELECT DISTINCT journal_id
                            FROM account_move
                            WHERE move_type = 'in_invoice'
                              AND journal_id IS NOT NULL
                            """)
        journal_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        journals = self.env['account.journal'].search_read(
            [('id', 'in', journal_ids)], ['id', 'name']
        )

        # Payment Terms
        self.env.cr.execute("""
                            SELECT DISTINCT invoice_payment_term_id
                            FROM account_move
                            WHERE move_type = 'in_invoice'
                              AND invoice_payment_term_id IS NOT NULL
                            """)
        term_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        payment_terms = self.env['account.payment.term'].search_read(
            [('id', 'in', term_ids)], ['id', 'name']
        )

        # Categories
        self.env.cr.execute("""
                            SELECT DISTINCT pt.categ_id
                            FROM account_move_line aml
                                     JOIN account_move am ON am.id = aml.move_id
                                     JOIN product_product pp ON pp.id = aml.product_id
                                     JOIN product_template pt ON pt.id = pp.product_tmpl_id
                            WHERE am.move_type = 'in_invoice'
                              AND aml.product_id IS NOT NULL
                              AND aml.display_type = 'product'
                            """)
        category_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        categories = self.env['product.category'].search_read(
            [('id', 'in', category_ids)], ['id', 'name']
        )

        # Locations
        self.env.cr.execute("""
                            SELECT DISTINCT pt2.default_location_dest_id
                            FROM account_move_line aml
                                     JOIN account_move am ON am.id = aml.move_id
                                     JOIN purchase_order_line pol ON pol.id = aml.purchase_line_id
                                     JOIN purchase_order po ON po.id = pol.order_id
                                     JOIN stock_picking_type pt2 ON pt2.id = po.picking_type_id
                            WHERE am.move_type = 'in_invoice'
                              AND aml.purchase_line_id IS NOT NULL
                              AND pt2.default_location_dest_id IS NOT NULL
                              AND aml.display_type = 'product'
                            """)
        location_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        locations = self.env['stock.location'].search_read(
            [('id', 'in', location_ids), ('usage', '=', 'internal')],
            ['id', 'display_name']
        )

        return {
            'vendors': vendors,
            'journals': journals,
            'payment_terms': payment_terms,
            'categories': categories,
            'locations': locations,
        }

    # =========================================================================
    # SECTION 2: Domain Builder
    # =========================================================================
    def _build_combined_domain(self, kwargs):
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

        # Date Filters
        if date_from or date_to:
            if date_from:
                base_domain.append(('invoice_date', '>=', fields.Date.to_date(date_from)))
            if date_to:
                base_domain.append(('invoice_date', '<=', fields.Date.to_date(date_to)))
        elif period and int(period) > 0:
            current_date_start = today - timedelta(days=int(period))
            base_domain.append(('invoice_date', '>=', current_date_start))
            base_domain.append(('invoice_date', '<=', today))

        # Sidebar Dropdown Filters
        if vendor_id and vendor_id != 'all':
            base_domain.append(('partner_id', '=', int(vendor_id)))
        if journal_id and journal_id != 'all':
            base_domain.append(('journal_id', '=', int(journal_id)))
        if payment_term_id and payment_term_id != 'all':
            base_domain.append(('invoice_payment_term_id', '=', int(payment_term_id)))
        if category_id and category_id != 'all':
            base_domain.append(('invoice_line_ids.product_id.categ_id', 'child_of', int(category_id)))
        if location_id and location_id != 'all':
            base_domain.append(
                ('invoice_line_ids.purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of',
                 int(location_id)))

        # Quick Filters
        if active_filters:
            states = []
            if active_filters.get('state_posted'): states.append('posted')
            if active_filters.get('state_draft'): states.append('draft')
            if states: base_domain.append(('state', 'in', states))

            payments = []
            if active_filters.get('pay_paid'): payments.append('paid')
            if active_filters.get('pay_not_paid'): payments.extend(['not_paid', 'partial'])
            if payments: base_domain.append(('payment_state', 'in', payments))

            if active_filters.get('is_overdue'):
                base_domain.extend([('state', '=', 'posted'), ('invoice_date_due', '<', today),
                                    ('payment_state', 'in', ['not_paid', 'partial'])])

            has_po = active_filters.get('has_po')
            no_po = active_filters.get('no_po')
            if has_po and not no_po:
                base_domain.append(('invoice_line_ids.purchase_line_id', '!=', False))
            elif no_po and not has_po:
                base_domain.append(('invoice_line_ids.purchase_line_id', '=', False))

        if native_domain:
            return expression.AND([base_domain, native_domain])
        return base_domain

    # =========================================================================
    # SECTION 3: Shared KPI Calculator
    # =========================================================================
    def _compute_kpis(self, bills, today):
        total_bills_count = len(bills)

        # Total Amount strictly for Posted Bills
        posted_bills = bills.filtered(lambda b: b.state == 'posted')
        total_bills_amount = sum(posted_bills.mapped('amount_total'))

        # Optimization: Filter once
        unpaid_bills = bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])
        posted_unpaid = posted_bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])

        upcoming_payables = sum(
            posted_unpaid.filtered(lambda b: b.invoice_date_due and b.invoice_date_due >= today).mapped(
                'amount_residual')
        )

        dpo_list = bills.filtered(lambda b: b.nova_payment_lead_time > 0).mapped('nova_payment_lead_time')
        avg_dpo = round(sum(dpo_list) / len(dpo_list)) if dpo_list else 0

        late_bills = posted_unpaid.filtered(lambda b: b.nova_overdue_days > 0)
        late_bills_ratio = round((len(late_bills) / len(posted_unpaid)) * 100) if posted_unpaid else 0

        # Fast No-PO calculation
        if bills:
            bills_with_po = self.env['account.move.line'].search([
                ('move_id', 'in', bills.ids),
                ('purchase_line_id', '!=', False),
                ('display_type', '=', 'product')
            ]).mapped('move_id')
            wo_po_count = total_bills_count - len(bills_with_po)
            wo_po_ratio = round((wo_po_count / total_bills_count) * 100) if total_bills_count else 0
        else:
            wo_po_count = 0
            wo_po_ratio = 0

        paid_amount = sum(bills.filtered(lambda b: b.payment_state == 'paid').mapped('amount_total'))
        unpaid_total = sum(unpaid_bills.mapped('amount_residual'))

        return {
            'total_bills_count': total_bills_count,
            'total_bills_amount': total_bills_amount,
            'upcoming_payables': upcoming_payables,
            'avg_dpo': avg_dpo,
            'late_bills_ratio': late_bills_ratio,
            'wo_po_ratio': wo_po_ratio,
            'wo_po_count': wo_po_count,
            'paid_amount': paid_amount,
            'unpaid_total': unpaid_total,
            'unpaid_bills': unpaid_bills,
        }

    # =========================================================================
    # SECTION 4: Main Dashboard Data Endpoint
    # =========================================================================
    @api.model
    def get_dashboard_data(self, **kwargs):
        today = fields.Date.context_today(self)
        domain = self._build_combined_domain(kwargs)
        bills = self.env['account.move'].search(domain)

        kpis = self._compute_kpis(bills, today)

        # Initialize Default Variables for Charts
        qty_pivot = []
        product_variances = {}
        overbilled_data = {}
        underbilled_data = {}

        trend_dict = {}
        trend_labels = []
        vendor_dict = {}
        lead_dict = {}

        if bills:
            # 1. Variance Calculations (In-Memory)
            bill_lines = self.env['account.move.line'].search([
                ('move_id', 'in', bills.ids),
                ('purchase_line_id', '!=', False),
                ('product_id', '!=', False),
                ('display_type', '=', 'product'),
            ])

            for line in bill_lines:
                prod_name = line.product_id.name or 'Unknown'

                if prod_name not in overbilled_data:
                    overbilled_data[prod_name] = 0
                if prod_name not in underbilled_data:
                    underbilled_data[prod_name] = 0

                if line.nova_qty_variance != 0:
                    product_variances[prod_name] = product_variances.get(prod_name, 0) + line.nova_qty_variance

                if line.nova_price_variance > 0:
                    overbilled_data[prod_name] += line.nova_price_variance
                elif line.nova_price_variance < 0:
                    underbilled_data[prod_name] += abs(line.nova_price_variance)

            for product, variance in product_variances.items():
                qty_pivot.append({'product': product, 'qty_variance': round(variance, 2)})
            qty_pivot = sorted(qty_pivot, key=lambda k: abs(k['qty_variance']), reverse=True)[:10]


            variance_products = sorted(
                list(set(list(overbilled_data.keys()) + list(underbilled_data.keys()))),
                key=lambda p: overbilled_data.get(p, 0) + underbilled_data.get(p, 0),
                reverse=True
            )[:10]

            overbilled_arr = [round(overbilled_data.get(p, 0), 2) for p in variance_products]
            underbilled_arr = [round(underbilled_data.get(p, 0), 2) for p in variance_products]
            # 2. Chart In-Memory Calculations
            sorted_bills = bills.sorted(key=lambda b: b.invoice_date or today)
            for bill in sorted_bills:

                # Trend Calculation ONLY for fully paid bills
                if bill.payment_state == 'paid' and bill.invoice_date:
                    month_key = bill.invoice_date.strftime('%B %Y')
                    if month_key not in trend_dict:
                        trend_dict[month_key] = 0
                        trend_labels.append(month_key)
                    trend_dict[month_key] += bill.amount_total

                # Vendor Calculation
                v_name = bill.partner_id.name or 'Unknown'
                vendor_dict[v_name] = vendor_dict.get(v_name, 0) + bill.amount_total

                # Lead Time Calculation (Strictly for paid bills)
                if bill.payment_state == 'paid':
                    if v_name not in lead_dict:
                        lead_dict[v_name] = {'days': 0, 'count': 0}
                    lead_dict[v_name]['days'] += bill.nova_payment_lead_time
                    lead_dict[v_name]['count'] += 1

        # Format arrays for JS
        trend_values = [trend_dict[l] for l in trend_labels]

        sorted_vendors = sorted(vendor_dict.items(), key=lambda x: x[1], reverse=True)[:10]
        vendor_labels = [x[0] for x in sorted_vendors]
        vendor_values = [x[1] for x in sorted_vendors]

        lead_arr = []
        for pname, data in lead_dict.items():
            avg_days = data['days'] / data['count'] if data['count'] > 0 else 0
            lead_arr.append({'vendor': pname, 'avg_days': round(avg_days)})

        lead_arr = sorted(lead_arr, key=lambda k: k['avg_days'], reverse=True)[:5]
        lead_labels = [x['vendor'] for x in lead_arr]
        lead_values = [x['avg_days'] for x in lead_arr]

        return {
            'cards': {
                'total_bills_count': kpis['total_bills_count'],
                'total_bills_amount': f"${kpis['total_bills_amount']:,.0f}",
                'upcoming_payables': f"${kpis['upcoming_payables']:,.0f}",
                'avg_dpo': kpis['avg_dpo'],
                'late_bills_ratio': kpis['late_bills_ratio'],
                'wo_po_ratio': kpis['wo_po_ratio'],
                'wo_po_count': kpis['wo_po_count'],
            },
            'tables': {
                'qty_variance_pivot': qty_pivot,
            },
            'charts': {
                'status': {
                    'labels': ['Paid', 'Unpaid'],
                    'datasets': [{'data': [kpis['paid_amount'], kpis['unpaid_total']],
                                  'backgroundColor': ['#2ECC71', '#E74C3C']}],
                },
                'trend': {
                    'labels': trend_labels,
                    'datasets': [
                        {'label': 'Total Spend (Paid Only)', 'data': trend_values, 'borderColor': '#3498DB',
                         'fill': False}],
                },
                'vendor': {
                    'labels': vendor_labels,
                    'datasets': [{'label': 'Amount', 'data': vendor_values, 'backgroundColor': '#27AE60'}],
                },
                'lead_time': {
                    'labels': lead_labels,
                    'datasets': [{'label': 'Avg Days', 'data': lead_values, 'backgroundColor': '#F39C12'}],
                },
                'price_var': {
                    'labels': variance_products if 'variance_products' in locals() else [],
                    'datasets': [
                        {'label': 'Overbilled (RED)', 'data': overbilled_arr if 'overbilled_arr' in locals() else [],
                         'backgroundColor': '#E74C3C'},
                        {'label': 'Underbilled/Savings (GREEN)',
                         'data': underbilled_arr if 'underbilled_arr' in locals() else [],
                         'backgroundColor': '#2ECC71'},
                    ],
                },
            },
        }

    # =========================================================================
    # SECTION 5: Excel Export
    # =========================================================================
    @api.model
    def export_bills_excel(self, **kwargs):
        if xlsxwriter is None:
            raise models.ValidationError("xlsxwriter is not installed. Run: pip install xlsxwriter")

        domain = self._build_combined_domain(kwargs)
        bills = self.env['account.move'].search(domain)
        today = fields.Date.context_today(self)
        kpis = self._compute_kpis(bills, today)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        title_fmt = workbook.add_format({'bold': True, 'font_size': 16, 'color': '#1e293b'})
        info_fmt = workbook.add_format({'italic': True, 'color': '#64748b', 'font_size': 10})
        kpi_hdr_fmt = workbook.add_format({'bold': True, 'bg_color': '#f8fafc', 'border': 1, 'font_color': '#475569'})
        kpi_val_fmt = workbook.add_format({'bold': True, 'border': 1, 'color': '#0f172a', 'align': 'center'})
        kpi_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'color': '#10b981', 'num_format': '#,##0.00', 'align': 'center'})
        kpi_danger_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'color': '#ef4444', 'num_format': '#,##0.00', 'align': 'center'})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        warning_fmt = workbook.add_format({'border': 1, 'align': 'center', 'font_color': '#ef4444', 'bold': True})
        italic_fmt = workbook.add_format({'italic': True, 'color': '#64748b'})

        # ── Sheet 1: Bills Overview
        sheet1 = workbook.add_worksheet('Bills Overview')
        sheet1.write('A1', 'Purchase Bills Analytical Report', title_fmt)

        journal_id = kwargs.get('journal_id', 'all')
        term_id = kwargs.get('payment_term_id', 'all')
        vendor_id = kwargs.get('vendor_id', 'all')
        journal_name = self.env['account.journal'].browse(int(journal_id)).name if journal_id != 'all' else 'All'
        term_name = self.env['account.payment.term'].browse(int(term_id)).name if term_id != 'all' else 'All'
        vendor_name = self.env['res.partner'].browse(int(vendor_id)).name if vendor_id != 'all' else 'All'

        sheet1.write('A2', f"Filters → Vendor: {vendor_name} | Journal: {journal_name} | Payment Term: {term_name}",
                     info_fmt)

        sheet1.write('A4', 'Total Bills Count', kpi_hdr_fmt)
        sheet1.write('B4', kpis['total_bills_count'], kpi_val_fmt)
        sheet1.write('A5', 'Total Billed Amount', kpi_hdr_fmt)
        sheet1.write('B5', kpis['total_bills_amount'], kpi_money_fmt)
        sheet1.write('A6', 'Average DPO (Days)', kpi_hdr_fmt)
        sheet1.write('B6', kpis['avg_dpo'], kpi_val_fmt)

        sheet1.write('D4', 'Upcoming Payables', kpi_hdr_fmt)
        sheet1.write('E4', kpis['upcoming_payables'], kpi_danger_fmt)
        sheet1.write('D5', 'Late Bills Ratio', kpi_hdr_fmt)
        sheet1.write('E5', f"{kpis['late_bills_ratio']}%", kpi_val_fmt)
        sheet1.write('D6', 'Bills Without PO', kpi_hdr_fmt)
        sheet1.write('E6', kpis['wo_po_count'], kpi_val_fmt)

        headers1 = ['Bill Number', 'Vendor', 'Source PO', 'Bill Date', 'Due Date', 'Total Amount', 'Amount Due',
                    'Lead Time (Days)', 'Overdue Days', 'Status', 'Payment Status']
        for col, header in enumerate(headers1):
            sheet1.write(7, col, header, header_fmt)
            sheet1.set_column(col, col, 18)
        sheet1.set_column(1, 1, 25)

        row = 8
        for bill in bills:
            product_lines = bill.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
            po_names = ", ".join(set(product_lines.mapped('purchase_line_id.order_id.name')))
            po_ref = bill.invoice_origin or (po_names if po_names else 'No PO (Maverick)')

            state_label = dict(bill._fields['state'].selection).get(bill.state, '')
            payment_label = dict(bill._fields['payment_state'].selection).get(bill.payment_state, '')

            sheet1.write(row, 0, bill.name or 'Draft', text_fmt)
            sheet1.write(row, 1, bill.partner_id.name or '', text_fmt)
            sheet1.write(row, 2, po_ref, text_fmt)
            sheet1.write(row, 3, str(bill.invoice_date or ''), text_fmt)
            sheet1.write(row, 4, str(bill.invoice_date_due or ''), text_fmt)
            sheet1.write(row, 5, bill.amount_total, money_fmt)
            sheet1.write(row, 6, bill.amount_residual, money_fmt)
            sheet1.write(row, 7, bill.nova_payment_lead_time, num_fmt)
            sheet1.write(row, 8, bill.nova_overdue_days, warning_fmt if bill.nova_overdue_days > 0 else num_fmt)
            sheet1.write(row, 9, state_label, text_fmt)
            sheet1.write(row, 10, payment_label, text_fmt)
            row += 1

        # ── Sheet 2: Invoice Line Variances
        sheet2 = workbook.add_worksheet('Invoice Line Variances')
        sheet2.write('A1', 'Detailed Product Variances (PO vs Bill)', title_fmt)
        sheet2.write('A2', 'Only lines with a price or quantity mismatch vs the linked PO are shown.', italic_fmt)

        headers2 = ['Bill Number', 'Vendor', 'Product', 'PO Price', 'Bill Price', 'Price Variance', 'PO Qty',
                    'Bill Qty', 'Qty Variance']
        for col, header in enumerate(headers2):
            sheet2.write(3, col, header, header_fmt)
            sheet2.set_column(col, col, 16)
        sheet2.set_column(2, 2, 35)

        if bills:
            bill_lines = self.env['account.move.line'].search([
                ('move_id', 'in', bills.ids),
                ('purchase_line_id', '!=', False),
                ('product_id', '!=', False),
                ('display_type', '=', 'product'),
            ])

            row2 = 4
            for line in bill_lines:
                if line.nova_price_variance != 0 or line.nova_qty_variance != 0:
                    sheet2.write(row2, 0, line.move_id.name or '', text_fmt)
                    sheet2.write(row2, 1, line.partner_id.name or '', text_fmt)
                    sheet2.write(row2, 2, line.product_id.name or '', text_fmt)
                    sheet2.write(row2, 3, line.nova_purchase_price_unit, money_fmt)
                    sheet2.write(row2, 4, line.price_unit, money_fmt)
                    sheet2.write(row2, 5, line.nova_price_variance,
                                 warning_fmt if line.nova_price_variance > 0 else money_fmt)
                    sheet2.write(row2, 6, line.purchase_line_id.product_qty, num_fmt)
                    sheet2.write(row2, 7, line.quantity, num_fmt)
                    sheet2.write(row2, 8, line.nova_qty_variance,
                                 warning_fmt if line.nova_qty_variance != 0 else num_fmt)
                    row2 += 1

        workbook.close()
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': f'Purchase_Analytics_{fields.Date.today()}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return attachment.id


# =============================================================================
# Custom Fields (100% Safe - store=False to prevent DB Crashes)
# =============================================================================
class AccountMove(models.Model):
    _inherit = 'account.move'

    nova_payment_lead_time = fields.Integer(
        compute='_compute_nova_payment_lead_time',
        string='Lead Time (Days)',
        store=False
    )

    nova_overdue_days = fields.Integer(
        compute='_compute_nova_overdue_days',
        string='Overdue Days',
        store=False
    )

    nova_total_price_variance = fields.Float(
        compute='_compute_nova_move_variances',
        string='Total Price Variance',
        store=False
    )

    nova_total_qty_variance = fields.Float(
        compute='_compute_nova_move_variances',
        string='Total Qty Variance',
        store=False
    )

    @api.depends('invoice_date', 'invoice_date_due', 'state')
    def _compute_nova_payment_lead_time(self):
        for move in self:
            if move.invoice_date and move.invoice_date_due:
                move.nova_payment_lead_time = (move.invoice_date_due - move.invoice_date).days
            else:
                move.nova_payment_lead_time = 0

    def _compute_nova_overdue_days(self):
        today = fields.Date.context_today(self)
        for move in self:
            if move.state == 'posted' and move.payment_state in ('not_paid',
                                                                 'partial') and move.invoice_date_due and move.invoice_date_due < today:
                move.nova_overdue_days = (today - move.invoice_date_due).days
            else:
                move.nova_overdue_days = 0

    @api.depends('invoice_line_ids.nova_price_variance', 'invoice_line_ids.nova_qty_variance')
    def _compute_nova_move_variances(self):
        for move in self:
            move.nova_total_price_variance = sum(move.invoice_line_ids.mapped('nova_price_variance'))
            move.nova_total_qty_variance = sum(move.invoice_line_ids.mapped('nova_qty_variance'))


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    nova_purchase_price_unit = fields.Float(
        compute='_compute_nova_variances',
        string='PO Price',
        store=False,
        digits='Product Price'
    )
    nova_price_variance = fields.Float(
        compute='_compute_nova_variances',
        string='Price Variance',
        store=False,
        digits='Product Price'
    )
    nova_qty_variance = fields.Float(
        compute='_compute_nova_variances',
        string='Qty Variance',
        store=False
    )
    nova_po_qty = fields.Float(
        compute='_compute_nova_variances',
        string="PO Quantity",
        store=False
    )

    nova_due_date = fields.Date(related='move_id.invoice_date_due', string="Due Date", store=False)
    nova_payment_ref = fields.Char(related='move_id.payment_reference', string="Payment Ref", store=False)

    @api.depends('purchase_line_id', 'purchase_line_id.price_unit', 'purchase_line_id.product_qty',
                 'purchase_line_id.product_uom', 'price_unit',
                 'quantity', 'product_uom_id', 'move_id.currency_id', 'move_id.invoice_date', 'move_id.move_type',
                 'display_type')
    def _compute_nova_variances(self):
        for line in self:
            if not line.purchase_line_id or line.move_id.move_type != 'in_invoice' or line.display_type != 'product':
                line.nova_purchase_price_unit = 0.0
                line.nova_price_variance = 0.0
                line.nova_qty_variance = 0.0
                line.nova_po_qty = 0.0
                continue

            po_uom = line.purchase_line_id.product_uom
            bill_uom = line.product_uom_id
            po_qty = line.purchase_line_id.product_qty

            if po_uom and bill_uom and po_uom != bill_uom:
                try:
                    po_qty = po_uom._compute_quantity(po_qty, bill_uom)
                except Exception:
                    pass

            line.nova_qty_variance = line.quantity - po_qty
            line.nova_po_qty = po_qty

            po_price = line.purchase_line_id.price_unit
            po_currency = line.purchase_line_id.currency_id
            bill_currency = line.currency_id or line.move_id.currency_id

            if po_currency and bill_currency and po_currency != bill_currency:
                company = line.company_id or line.move_id.company_id or self.env.company
                conversion_date = line.move_id.invoice_date or fields.Date.context_today(line)
                try:
                    po_price = po_currency._convert(
                        po_price, bill_currency, company, conversion_date
                    )
                except Exception:
                    pass

            line.nova_purchase_price_unit = po_price
            expected_cost = po_price * line.quantity
            actual_cost = line.price_subtotal
            line.nova_price_variance = actual_cost - expected_cost