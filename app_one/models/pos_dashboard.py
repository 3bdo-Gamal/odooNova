from odoo import models, fields, api
from odoo.osv import expression
from datetime import datetime, timedelta
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class PosDashboard(models.Model):
    _name = 'wb.pos.dashboard'
    _description = 'POS KPI Dashboard'

    # Security Whitelists
    ALLOWED_FIELDS = {
        'name', 'pos_reference', 'state', 'date_order', 'amount_total', 'amount_tax',
        'partner_id', 'user_id', 'session_id', 'config_id', 'company_id'
    }

    ALLOWED_OPERATORS = {
        '=', '!=', 'ilike', 'not ilike', '<', '>', '<=', '>=', 'in', 'not in'
    }

    def _get_field_display_value(self, record, field_name):
        field = record._fields.get(field_name)
        if not field: return 'Unknown'
        val = record[field_name]
        if not val and val != 0: return 'None'

        if field.type == 'many2one':
            return val.display_name
        elif field.type == 'selection':
            return dict(field.selection).get(val, val)
        elif field.type in ['date', 'datetime']:
            return val.strftime('%Y-%m-%d')
        else:
            return str(val)

    def _serialize_domain(self, domain):
        res = []
        for term in domain:
            if isinstance(term, (list, tuple)) and len(term) == 3:
                val = term[2]
                if isinstance(val, datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(val, fields.Date):
                    val = val.strftime('%Y-%m-%d')
                res.append([term[0], term[1], val])
            else:
                res.append(term)
        return res

    @api.model
    def get_filter_options(self):
        pos_configs = self.env['pos.config'].search_read([], ['id', 'name'])
        users = self.env['res.users'].search_read([('share', '=', False)], ['id', 'name'])
        categories = self.env['product.category'].search_read([], ['id', 'name'])
        payment_methods = self.env['pos.payment.method'].search_read([], ['id', 'name'])

        # Get Whitelisted Fields for Custom Filters & Grouping
        fields_data = self.env['pos.order'].fields_get(list(self.ALLOWED_FIELDS))
        model_fields = []
        for fname, fdata in fields_data.items():
            if fdata.get('searchable') or fdata.get('store'):
                model_fields.append({
                    'name': fname, 'string': fdata.get('string'),
                    'type': fdata.get('type'), 'selection': fdata.get('selection', [])
                })
        model_fields = sorted(model_fields, key=lambda x: x['string'])

        return {
            'pos_configs': pos_configs, 'users': users,
            'categories': categories, 'payment_methods': payment_methods,
            'model_fields': model_fields
        }

    @api.model
    def get_pos_dashboard_data(self, **kwargs):
        period = kwargs.get('period', 7)
        date_from = kwargs.get('date_from', False)
        date_to = kwargs.get('date_to', False)
        config_id = kwargs.get('config_id', 'all')
        user_id = kwargs.get('user_id', 'all')
        category_id = kwargs.get('category_id', 'all')
        company_id = kwargs.get('company_id', 'all')
        state = kwargs.get('state', 'paid')
        payment_method_id = kwargs.get('payment_method_id', 'all')
        top_products_limit = int(kwargs.get('top_products', 5))

        # Advanced Search Args
        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])
        group_by_list = kwargs.get('group_by_list', [])

        # Time logic
        if date_from and date_to:
            current_date_start = datetime.strptime(date_from, '%Y-%m-%d')
            current_date_end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            if current_date_start > current_date_end:
                current_date_start, current_date_end = current_date_end, current_date_start
        else:
            period = int(period) if period and int(period) > 0 else 7
            current_date_end = fields.Datetime.now()
            current_date_start = current_date_end - timedelta(days=period)

        time_domain = [('date_order', '>=', current_date_start), ('date_order', '<=', current_date_end)]
        and_tuples = []

        # Standard Filters
        if config_id and config_id != 'all': and_tuples.append(('session_id.config_id', '=', int(config_id)))
        if user_id and user_id != 'all': and_tuples.append(('user_id', '=', int(user_id)))
        if category_id and category_id != 'all': and_tuples.append(
            ('lines.product_id.categ_id', 'child_of', int(category_id)))
        if company_id and company_id != 'all': and_tuples.append(('company_id', '=', int(company_id)))
        if payment_method_id and payment_method_id != 'all': and_tuples.append(
            ('payment_ids.payment_method_id', '=', int(payment_method_id)))

        # Active UI Filters
        if active_filters.get('my_orders'): and_tuples.append(('user_id', '=', self.env.uid))

        # State Filter
        if state and state != 'all':
            and_tuples.append(('state', '=', state))
        else:
            and_tuples.append(('state', '!=', 'cancel'))

        # Custom Domain Parsing
        if custom_domain_list:
            for c_filter in custom_domain_list:
                f_name, op, val, f_type = c_filter.get('field'), c_filter.get('operator'), c_filter.get(
                    'value'), c_filter.get('type')
                if f_name not in self.ALLOWED_FIELDS or op not in self.ALLOWED_OPERATORS: continue
                if f_type in ['integer', 'float', 'monetary'] and isinstance(val, str) and val.replace('.', '',
                                                                                                       1).isdigit():
                    val = float(val)
                elif f_type == 'boolean':
                    val = True if str(val) == '1' else False
                and_tuples.append((f_name, op, val))

        final_domain_list = [time_domain]
        if and_tuples:
            final_domain_list.append(and_tuples)

        # Search Query
        if search_query:
            search_domain = ['|', '|', ('name', 'ilike', search_query), ('pos_reference', 'ilike', search_query),
                             ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)

        nav_domain = expression.AND(final_domain_list)
        orders = self.env['pos.order'].search(nav_domain)

        # KPI Calculations
        pos_revenue = sum(orders.mapped('amount_total'))
        pos_orders_count = len(orders)
        gross_sales = sum(o.amount_total for o in orders if o.amount_total > 0)
        refunded_amount = sum(abs(o.amount_total) for o in orders if o.amount_total < 0)

        total_discount = 0
        hourly_sales = {str(i).zfill(2): 0 for i in range(24)}
        product_sales = {}

        for order in orders:
            if order.date_order:
                hour = order.date_order.strftime('%H')
                hourly_sales[hour] += order.amount_total
            for line in order.lines:
                p_name = line.product_id.name or 'Unknown'
                product_sales[p_name] = product_sales.get(p_name, 0) + line.qty
                if line.discount > 0:
                    total_discount += (line.price_unit * line.qty) * (line.discount / 100)

        # Payment Logic
        total_cash, total_card = 0, 0
        for payment in orders.mapped('payment_ids'):
            if payment.payment_method_id.journal_id.type == 'cash':
                total_cash += payment.amount
            elif payment.payment_method_id.journal_id.type == 'bank':
                total_card += payment.amount

        total_payments = total_cash + total_card
        cash_ratio = (total_cash / total_payments * 100) if total_payments > 0 else 0
        card_ratio = (total_card / total_payments * 100) if total_payments > 0 else 0
        discount_pct = (total_discount / gross_sales * 100) if gross_sales > 0 else 0
        refund_rate = (refunded_amount / gross_sales * 100) if gross_sales > 0 else 0

        # Dynamic Group By Logic
        dynamic_chart_labels, dynamic_chart_data = [], []
        if group_by_list:
            dynamic_chart_dict = {}
            for order in orders:
                label_parts = [str(self._get_field_display_value(order, gb)) for gb in group_by_list if
                               gb in self.ALLOWED_FIELDS]
                if label_parts:
                    label = " / ".join(label_parts)
                    dynamic_chart_dict[label] = dynamic_chart_dict.get(label, 0) + order.amount_total
            dynamic_chart_labels = list(dynamic_chart_dict.keys())
            dynamic_chart_data = [round(val, 2) for val in dynamic_chart_dict.values()]

        sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:top_products_limit]
        safe_nav_domain = self._serialize_domain(nav_domain)

        return {
            'pos_revenue': round(pos_revenue, 2), 'pos_orders_count': pos_orders_count,
            'cash_ratio': round(cash_ratio, 2), 'card_ratio': round(card_ratio, 2),
            'discount_pct': round(discount_pct, 2), 'refund_rate': round(refund_rate, 2),
            'hourly_labels': list(hourly_sales.keys()), 'hourly_data': [round(val, 2) for val in hourly_sales.values()],
            'product_labels': [i[0] for i in sorted_products], 'product_data': [i[1] for i in sorted_products],
            'dynamic_chart_labels': dynamic_chart_labels, 'dynamic_chart_data': dynamic_chart_data,
            'nav_domain': safe_nav_domain,
        }

    @api.model
    def export_custom_pivot_excel(self, **kwargs):
        if not xlsxwriter:
            return {'error': 'xlsxwriter library is not installed on the server.'}

        date_from, date_to = kwargs.get('date_from'), kwargs.get('date_to')
        config_id, user_id = kwargs.get('config_id'), kwargs.get('user_id')
        category_id, company_id = kwargs.get('category_id'), kwargs.get('company_id')
        payment_method_id = kwargs.get('payment_method_id', 'all')
        detailed_excel = kwargs.get('detailed_excel', False)
        state = kwargs.get('state', 'all')

        # Advanced Search Args
        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])

        and_tuples = []
        if date_from and date_to:
            and_tuples += [('date_order', '>=', f"{date_from} 00:00:00"), ('date_order', '<=', f"{date_to} 23:59:59")]

        if config_id and config_id != 'all': and_tuples.append(('session_id.config_id', '=', int(config_id)))
        if user_id and user_id != 'all': and_tuples.append(('user_id', '=', int(user_id)))
        if category_id and category_id != 'all': and_tuples.append(
            ('lines.product_id.categ_id', 'child_of', int(category_id)))
        if company_id and company_id != 'all': and_tuples.append(('company_id', '=', int(company_id)))
        if payment_method_id and payment_method_id != 'all': and_tuples.append(
            ('payment_ids.payment_method_id', '=', int(payment_method_id)))

        # Active UI Filters
        if active_filters.get('my_orders'): and_tuples.append(('user_id', '=', self.env.uid))

        if state and state != 'all':
            and_tuples.append(('state', '=', state))
        else:
            and_tuples.append(('state', '!=', 'cancel'))

        # Custom Domain Parsing
        if custom_domain_list:
            for c_filter in custom_domain_list:
                f_name, op, val, f_type = c_filter.get('field'), c_filter.get('operator'), c_filter.get(
                    'value'), c_filter.get('type')
                if f_name not in self.ALLOWED_FIELDS or op not in self.ALLOWED_OPERATORS: continue
                if f_type in ['integer', 'float', 'monetary'] and isinstance(val, str) and val.replace('.', '',
                                                                                                       1).isdigit():
                    val = float(val)
                elif f_type == 'boolean':
                    val = True if str(val) == '1' else False
                and_tuples.append((f_name, op, val))

        final_domain_list = []
        if and_tuples:
            final_domain_list.append(and_tuples)

        if search_query:
            search_domain = ['|', '|', ('name', 'ilike', search_query), ('pos_reference', 'ilike', search_query),
                             ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)

        domain = expression.AND(final_domain_list) if final_domain_list else []
        orders = self.env['pos.order'].search(domain)

        export_group = kwargs.get('export_group', 'user_id')
        export_measures = kwargs.get('export_measures', ['revenue'])

        pivot_data = {}
        for order in orders:
            key = 'Unknown'
            if export_group == 'partner_id':
                key = order.partner_id.name or 'Walk-in Customer'
            elif export_group == 'user_id':
                key = order.user_id.name or 'Unknown'
            elif export_group == 'config_id':
                key = order.session_id.config_id.name or 'Unknown'

            if export_group in ['product_id', 'categ_id']:
                for line in order.lines:
                    line_key = line.product_id.name if export_group == 'product_id' else line.product_id.categ_id.name
                    line_key = line_key or 'Unknown'
                    if line_key not in pivot_data:
                        pivot_data[line_key] = {'revenue': 0, 'qty': 0, 'discount': 0, 'orders': set(), 'lines': []}

                    pivot_data[line_key]['revenue'] += line.price_subtotal_incl
                    pivot_data[line_key]['qty'] += line.qty
                    disc = (line.price_unit * line.qty) * (line.discount / 100) if line.discount else 0
                    pivot_data[line_key]['discount'] += disc
                    pivot_data[line_key]['orders'].add(order.id)

                    if detailed_excel:
                        pivot_data[line_key]['lines'].append({
                            'name': order.pos_reference or order.name, 'revenue': line.price_subtotal_incl,
                            'qty': line.qty, 'discount': disc, 'date': str(order.date_order.date())
                        })
            else:
                if key not in pivot_data:
                    pivot_data[key] = {'revenue': 0, 'qty': 0, 'discount': 0, 'orders': set(), 'lines': []}

                pivot_data[key]['revenue'] += order.amount_total
                pivot_data[key]['orders'].add(order.id)
                order_disc, order_qty = 0, 0

                for line in order.lines:
                    order_qty += line.qty
                    if line.discount > 0:
                        order_disc += (line.price_unit * line.qty) * (line.discount / 100)

                pivot_data[key]['qty'] += order_qty
                pivot_data[key]['discount'] += order_disc

                if detailed_excel:
                    pivot_data[key]['lines'].append({
                        'name': order.pos_reference or order.name, 'revenue': order.amount_total,
                        'qty': order_qty, 'discount': order_disc, 'date': str(order.date_order.date())
                    })

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('POS Pivot Analysis')
        if detailed_excel: sheet.outline_settings(symbols_below=False)

        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_format = workbook.add_format({'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f8fafc'})
        detail_text_format = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})
        detail_money_format = workbook.add_format(
            {'num_format': '#,##0.00', 'border': 1, 'font_color': '#475569', 'bg_color': '#ffffff'})

        group_titles = {'config_id': 'POS Point', 'user_id': 'Cashier', 'product_id': 'Product', 'categ_id': 'Category'}
        headers = [group_titles.get(export_group, 'Group')]

        if 'revenue' in export_measures: headers.append('Total Revenue (EGP)')
        if 'qty' in export_measures: headers.append('Quantity Sold')
        if 'discount' in export_measures: headers.append('Total Discounts')
        headers.append('Orders Count')

        for col_num, header in enumerate(headers):
            sheet.write(0, col_num, header, header_format)
            sheet.set_column(col_num, col_num, 35 if col_num == 0 else 18)

        row = 1
        for k, data in sorted(pivot_data.items(), key=lambda x: x[1]['revenue'], reverse=True):
            sheet.write(row, 0, str(k), text_format)
            col = 1
            if 'revenue' in export_measures: sheet.write(row, col, data['revenue'], money_format); col += 1
            if 'qty' in export_measures: sheet.write(row, col, data['qty'], num_format); col += 1
            if 'discount' in export_measures: sheet.write(row, col, data['discount'], money_format); col += 1
            sheet.write(row, col, len(data['orders']), num_format)

            if detailed_excel and 'lines' in data:
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0, f"   ↳ {line['name']} ({line['date']})", detail_text_format)
                    col = 1
                    if 'revenue' in export_measures: sheet.write(row, col, line['revenue'],
                                                                 detail_money_format); col += 1
                    if 'qty' in export_measures: sheet.write(row, col, line['qty'], detail_money_format); col += 1
                    if 'discount' in export_measures: sheet.write(row, col, line['discount'],
                                                                  detail_money_format); col += 1
                    sheet.write(row, col, 1, detail_money_format)
                    sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                    row += 1
            else:
                row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'POS_Export_{fields.Date.today()}.xlsx', 'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id