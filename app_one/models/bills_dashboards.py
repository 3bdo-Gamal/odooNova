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
                # Use extend to properly append the NOT condition
                base_domain.extend(['!', ('invoice_line_ids.purchase_line_id', '!=', False)])

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

        # --- VALUE-BASED LATE BILLS RATIO FIX ---
        late_bills = posted_unpaid.filtered(lambda b: b.nova_overdue_days > 0)

        # Calculate ratio based on residual amount (debt) instead of record count
        late_bills_amount = sum(late_bills.mapped('amount_residual'))
        total_unpaid_amount = sum(posted_unpaid.mapped('amount_residual'))

        late_bills_ratio = round((late_bills_amount / total_unpaid_amount) * 100) if total_unpaid_amount > 0 else 0
        # ----------------------------------------

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
        price_variance_line_ids = []
        qty_variance_line_ids = []

        trend_dict = {}
        trend_labels = []
        vendor_dict = {}
        lead_dict = {}

        if bills:
            # Variance Calculations (In-Memory)
            bill_lines = self.env['account.move.line'].search([
                ('move_id', 'in', bills.ids),
                ('purchase_line_id', '!=', False),
                ('product_id', '!=', False),
                ('display_type', 'in', ('product', False)),
            ])

            for line in bill_lines:
                prod_name = line.product_id.name or 'Unknown'

                if abs(line.nova_qty_variance) > 0.01:
                    qty_variance_line_ids.append(line.id)
                    product_variances[prod_name] = product_variances.get(prod_name, 0) + line.nova_qty_variance

                if abs(line.nova_price_variance) > 0.01:
                    price_variance_line_ids.append(line.id)

                    if prod_name not in overbilled_data:
                        overbilled_data[prod_name] = 0
                    if prod_name not in underbilled_data:
                        underbilled_data[prod_name] = 0

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

            # Chart In-Memory Calculations
            sorted_bills = bills.sorted(key=lambda b: b.invoice_date or today)
            for bill in sorted_bills:
                if bill.payment_state == 'paid' and bill.invoice_date:
                    month_key = bill.invoice_date.strftime('%B %Y')
                    if month_key not in trend_dict:
                        trend_dict[month_key] = 0
                        trend_labels.append(month_key)
                    trend_dict[month_key] += bill.amount_total

                v_name = bill.partner_id.name or 'Unknown'
                vendor_dict[v_name] = vendor_dict.get(v_name, 0) + bill.amount_total

                if bill.payment_state == 'paid':
                    if v_name not in lead_dict:
                        lead_dict[v_name] = {'days': 0, 'count': 0}
                    lead_dict[v_name]['days'] += bill.nova_payment_lead_time
                    lead_dict[v_name]['count'] += 1

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
            'price_variance_line_ids': price_variance_line_ids,
            'qty_variance_line_ids': qty_variance_line_ids,
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

        export_group = kwargs.get('export_group', 'partner_id')
        export_measures = kwargs.get('export_measures', ['amount'])
        detailed_excel = kwargs.get('detailed_excel', False)

        # Build pivot data structure
        pivot_data = {}
        for bill in bills:
            key = 'Unknown'
            if export_group == 'partner_id':
                key = bill.partner_id.name or 'Unknown'
            elif export_group == 'invoice_user_id':
                key = bill.invoice_user_id.name or 'Unknown'
            elif export_group == 'date:month':
                key = bill.invoice_date.strftime('%B %Y') if bill.invoice_date else 'Unknown'

            # If grouped by line-level items (product, category)
            if export_group in ['product_id', 'categ_id']:
                for line in bill.invoice_line_ids:
                    if line.display_type not in ('product', False):
                        continue

                    if export_group == 'product_id':
                        line_key = line.product_id.name or 'Unknown'
                    else:
                        raw_cat_name = line.product_id.categ_id.complete_name or 'Uncategorized'
                        if raw_cat_name.startswith('All / '):
                            line_key = raw_cat_name.replace('All / ', '', 1)
                        else:
                            line_key = raw_cat_name

                    if line_key not in pivot_data:
                        pivot_data[line_key] = {'amount': 0, 'qty': 0, 'price_var': 0, 'qty_var': 0, 'bills': set(),
                                                'lines': []}

                    pivot_data[line_key]['amount'] += line.price_subtotal
                    pivot_data[line_key]['qty'] += line.quantity
                    pivot_data[line_key]['price_var'] += line.nova_price_variance
                    pivot_data[line_key]['qty_var'] += line.nova_qty_variance
                    pivot_data[line_key]['bills'].add(bill.id)

                    if detailed_excel:
                        pivot_data[line_key]['lines'].append({
                            'name': bill.name,
                            'amount': line.price_subtotal,
                            'qty': line.quantity,
                            'price_var': line.nova_price_variance,
                            'qty_var': line.nova_qty_variance,
                            'date': str(bill.invoice_date)
                        })
            else:
                # Grouped by header-level items (vendor, user, month)
                if key not in pivot_data:
                    pivot_data[key] = {'amount': 0, 'qty': 0, 'price_var': 0, 'qty_var': 0, 'bills': set(), 'lines': []}

                pivot_data[key]['amount'] += bill.amount_untaxed
                pivot_data[key]['bills'].add(bill.id)

                bill_qty, bill_price_var, bill_qty_var = 0, 0, 0
                for line in bill.invoice_line_ids:
                    if line.display_type not in ('product', False):
                        continue
                    bill_qty += line.quantity
                    bill_price_var += line.nova_price_variance
                    bill_qty_var += line.nova_qty_variance

                pivot_data[key]['qty'] += bill_qty
                pivot_data[key]['price_var'] += bill_price_var
                pivot_data[key]['qty_var'] += bill_qty_var

                if detailed_excel:
                    pivot_data[key]['lines'].append({
                        'name': bill.name,
                        'amount': bill.amount_untaxed,
                        'qty': bill_qty,
                        'price_var': bill_price_var,
                        'qty_var': bill_qty_var,
                        'date': str(bill.invoice_date)
                    })

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Bills Analytics')

        if detailed_excel:
            sheet.outline_settings(symbols_below=False)

        # Styles
        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_format = workbook.add_format({'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f8fafc'})
        detail_text_format = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})
        detail_money_format = workbook.add_format(
            {'num_format': '#,##0.00', 'border': 1, 'font_color': '#475569', 'bg_color': '#ffffff'})

        group_titles = {'partner_id': 'Vendor', 'product_id': 'Product', 'categ_id': 'Category',
                        'invoice_user_id': 'Purchase Rep', 'date:month': 'Month'}
        headers = [group_titles.get(export_group, 'Group')]

        if 'amount' in export_measures: headers.append('Total Amount (EGP)')
        if 'qty' in export_measures: headers.append('Billed Quantity')
        if 'price_var' in export_measures: headers.append('Price Variance')
        if 'qty_var' in export_measures: headers.append('Quantity Variance')
        if 'bill_count' in export_measures: headers.append('Bills Count')
        if 'abv' in export_measures: headers.append('Avg Bill Value')

        for col_num, header in enumerate(headers):
            sheet.write(0, col_num, header, header_format)
            sheet.set_column(col_num, col_num, 35 if col_num == 0 else 18)

        row = 1
        for k, data in sorted(pivot_data.items(), key=lambda x: x[1]['amount'], reverse=True):
            sheet.write(row, 0, str(k), text_format)
            col = 1
            if 'amount' in export_measures: sheet.write(row, col, data['amount'], money_format); col += 1
            if 'qty' in export_measures: sheet.write(row, col, data['qty'], num_format); col += 1
            if 'price_var' in export_measures: sheet.write(row, col, data['price_var'], money_format); col += 1
            if 'qty_var' in export_measures: sheet.write(row, col, data['qty_var'], num_format); col += 1
            if 'bill_count' in export_measures: sheet.write(row, col, len(data['bills']), num_format); col += 1
            if 'abv' in export_measures:
                abv_val = data['amount'] / len(data['bills']) if len(data['bills']) > 0 else 0
                sheet.write(row, col, abv_val, money_format);
                col += 1

            # Render expanded detailed lines
            if detailed_excel and 'lines' in data:
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0, f"   ↳ {line['name']} ({line['date']})", detail_text_format)
                    col = 1
                    if 'amount' in export_measures: sheet.write(row, col, line['amount'], detail_money_format); col += 1
                    if 'qty' in export_measures: sheet.write(row, col, line['qty'], detail_money_format); col += 1
                    if 'price_var' in export_measures: sheet.write(row, col, line['price_var'],
                                                                   detail_money_format); col += 1
                    if 'qty_var' in export_measures: sheet.write(row, col, line['qty_var'],
                                                                 detail_money_format); col += 1
                    if 'bill_count' in export_measures: sheet.write(row, col, 1, detail_money_format); col += 1
                    if 'abv' in export_measures: sheet.write(row, col, line['amount'], detail_money_format); col += 1

                    sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                    row += 1
            else:
                row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'Bills_Analytics_Export_{fields.Date.today()}.xlsx', 'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
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

    nova_payment_state = fields.Selection(related='move_id.payment_state', string="Payment Status", store=False)

    nova_qty_financial_variance = fields.Float(
        compute='_compute_nova_variances',
        string='Qty Financial Variance',
        store=False
    )

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
            if not line.purchase_line_id or line.move_id.move_type != 'in_invoice' or line.display_type not in (
                    'product', False):
                line.nova_purchase_price_unit = 0.0
                line.nova_price_variance = 0.0
                line.nova_qty_variance = 0.0
                line.nova_po_qty = 0.0
                line.nova_qty_financial_variance = 0.0
                continue

            po_uom = line.purchase_line_id.product_uom
            bill_uom = line.product_uom_id
            po_qty = line.purchase_line_id.product_qty
            po_price = line.purchase_line_id.price_unit

            if po_uom and bill_uom and po_uom != bill_uom:
                try:
                    po_qty = po_uom._compute_quantity(po_qty, bill_uom)
                    po_price = po_uom._compute_price(po_price, bill_uom)
                except Exception:
                    pass

            line.nova_qty_variance = line.quantity - po_qty
            line.nova_po_qty = po_qty

            po_currency = line.purchase_line_id.currency_id
            bill_currency = line.currency_id or line.move_id.currency_id

            if po_currency and bill_currency and po_currency != bill_currency:
                company = line.company_id or line.move_id.company_id or self.env.company
                conversion_date = line.move_id.invoice_date or fields.Date.context_today(line)
                try:
                    po_price = po_currency._convert(po_price, bill_currency, company, conversion_date)
                except Exception:
                    pass

            line.nova_purchase_price_unit = po_price

            line.nova_qty_financial_variance = line.nova_qty_variance * po_price

            # Calculate exact financial variance
            expected_cost = po_price * line.quantity
            actual_cost = line.price_subtotal
            variance = actual_cost - expected_cost

            line.nova_price_variance = variance if abs(variance) > 0.01 else 0.0