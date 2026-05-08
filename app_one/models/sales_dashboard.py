from odoo import models, fields, api
from datetime import datetime, timedelta, date
from odoo.osv import expression
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class SalesDashboard(models.Model):
    _name = 'wb.sales.dashboard'
    _description = 'Sales KPI Dashboard'

    #  Whitelist
    ALLOWED_FIELDS = {
        'name', 'state', 'date_order', 'amount_total', 'amount_untaxed',
        'partner_id', 'user_id', 'team_id', 'company_id', 'warehouse_id',
        'client_order_ref', 'invoice_status'
    }

    ALLOWED_OPERATORS = {
        '=', '!=', 'ilike', 'not ilike',
        '<', '>', '<=', '>=', 'in', 'not in'
    }

    @api.model
    def get_filter_options(self):
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        users = self.env['res.users'].search_read([('share', '=', False)], ['id', 'name'])
        teams = self.env['crm.team'].search_read([], ['id', 'name'])

        categories = []
        for c in self.env['product.category'].search([]):
            clean_name = c.display_name
            if clean_name.startswith('All / '):
                clean_name = clean_name.replace('All / ', '', 1)
            categories.append({'id': c.id, 'name': clean_name})

        countries = self.env['res.country'].search_read([], ['id', 'name'])
        companies = self.env['res.company'].search_read([], ['id', 'name'])

        #  Whitelist
        fields_data = self.env['sale.order'].fields_get(list(self.ALLOWED_FIELDS))
        model_fields = []
        for fname, fdata in fields_data.items():
            if fdata.get('searchable') or fdata.get('store'):
                model_fields.append({
                    'name': fname,
                    'string': fdata.get('string'),
                    'type': fdata.get('type'),
                    'selection': fdata.get('selection', [])
                })
        model_fields = sorted(model_fields, key=lambda x: x['string'])

        return {
            'warehouses': warehouses, 'users': users, 'teams': teams,
            'categories': categories, 'countries': countries, 'companies': companies,
            'model_fields': model_fields
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
            # إصلاح الـ Bug الخاص بـ nested tuples/lists ليطابق Odoo Domain
            if isinstance(term, (list, tuple)) and len(term) == 3:
                val = term[2]
                if isinstance(val, datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(val, date):
                    val = val.strftime('%Y-%m-%d')
                res.append([term[0], term[1], val])
            else:
                res.append(term)
        return res

    @api.model
    def get_sales_dashboard_data(self, **kwargs):
        period = kwargs.get('period', 7)
        date_from = kwargs.get('date_from', False)
        date_to = kwargs.get('date_to', False)
        warehouse_id = kwargs.get('warehouse_id', 'all')
        user_id = kwargs.get('user_id', 'all')
        state = kwargs.get('state', 'all')
        team_id = kwargs.get('team_id', 'all')
        category_id = kwargs.get('category_id', 'all')
        country_id = kwargs.get('country_id', 'all')
        company_id = kwargs.get('company_id', 'all')

        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])
        group_by_list = kwargs.get('group_by_list', [])

        top_products_limit = int(kwargs.get('top_products', 5))
        top_customers_limit = int(kwargs.get('top_customers', 5))
        top_salespeople_limit = int(kwargs.get('top_salespeople', 5))
        top_categories_limit = int(kwargs.get('top_categories', 5))

        if date_from and date_to:
            current_date_start = datetime.strptime(date_from, '%Y-%m-%d')
            current_date_end = datetime.strptime(date_to, '%Y-%m-%d')
            if current_date_start > current_date_end:
                current_date_start, current_date_end = current_date_end, current_date_start

            current_date_start = current_date_start.replace(hour=0, minute=0, second=0)
            current_date_end = current_date_end.replace(hour=23, minute=59, second=59)

            delta_days = (current_date_end - current_date_start).days + 1
            previous_date_end = current_date_start - timedelta(seconds=1)
            previous_date_start = previous_date_end - timedelta(days=delta_days)
        else:
            period = int(period) if period and int(period) > 0 else 7
            current_date_end = fields.Datetime.now()
            current_date_start = current_date_end - timedelta(days=period)
            previous_date_end = current_date_start - timedelta(seconds=1)
            previous_date_start = previous_date_end - timedelta(days=period)

        time_domain = [('date_order', '>=', current_date_start), ('date_order', '<=', current_date_end)]
        prev_time_domain = [('date_order', '>=', previous_date_start), ('date_order', '<=', previous_date_end)]

        and_tuples = []
        if warehouse_id and warehouse_id != 'all': and_tuples.append(('warehouse_id', '=', int(warehouse_id)))
        if user_id and user_id != 'all': and_tuples.append(('user_id', '=', int(user_id)))
        if team_id and team_id != 'all': and_tuples.append(('team_id', '=', int(team_id)))
        if category_id and category_id != 'all': and_tuples.append(
            ('order_line.product_id.categ_id', 'child_of', int(category_id)))
        if country_id and country_id != 'all': and_tuples.append(('partner_id.country_id', '=', int(country_id)))
        if company_id and company_id != 'all': and_tuples.append(('company_id', '=', int(company_id)))

        if active_filters.get('my_orders'): and_tuples.append(('user_id', '=', self.env.uid))
        if active_filters.get('to_invoice'): and_tuples.append(('invoice_status', '=', 'to invoice'))

        # 2. State filter في SQL مباشرة (بدل الـ Python filtered) لحماية الذاكرة (Performance Fix)
        if active_filters.get('quotations') or state == 'quotation':
            and_tuples.append(('state', 'in', ['draft', 'sent']))
        elif active_filters.get('sales_orders') or state == 'sale':
            and_tuples.append(('state', 'in', ['sale', 'done']))
        else:
            and_tuples.append(('state', '!=', 'cancel'))

        valid_operators = self.ALLOWED_OPERATORS
        valid_fields = self.ALLOWED_FIELDS

        if custom_domain_list:
            for c_filter in custom_domain_list:
                f_name = c_filter.get('field')
                op = c_filter.get('operator')
                val = c_filter.get('value')
                f_type = c_filter.get('type')

                if f_name not in valid_fields or op not in valid_operators:
                    continue

                if f_type in ['integer', 'float', 'monetary'] and isinstance(val, str) and val.replace('.', '',
                                                                                                       1).isdigit():
                    val = float(val)
                elif f_type == 'boolean':
                    val = True if str(val) == '1' else False
                and_tuples.append((f_name, op, val))

        final_domain_list = [time_domain]
        prev_domain_list = [prev_time_domain]

        if and_tuples:
            final_domain_list.append(and_tuples)
            prev_domain_list.append(and_tuples)

        if search_query:
            search_domain = ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)
            prev_domain_list.append(search_domain)

        nav_domain = expression.AND(final_domain_list)
        #  SQL Domain
        orders = self.env['sale.order'].search(nav_domain)

        # 1. Total Revenue & AOV
        total_revenue = sum(orders.mapped('amount_untaxed'))
        total_orders = len(orders)
        aov = total_revenue / total_orders if total_orders > 0 else 0

        # Growth Calculation
        prev_nav_domain = expression.AND(prev_domain_list)
        prev_agg = self.env['sale.order'].read_group(
            prev_nav_domain, ['amount_untaxed:sum'], []
        )
        prev_revenue = prev_agg[0].get('amount_untaxed', 0) if prev_agg else 0
        if prev_revenue > 0:
            sales_growth = ((total_revenue - prev_revenue) / prev_revenue) * 100
        elif total_revenue > 0:
            sales_growth = 100.0
        else:
            sales_growth = 0.0

        # 2. Cost, Discount & Profit (WITH PREFETCH FIX)
        total_cost = 0
        total_discount = 0
        has_purchase_price = 'purchase_price' in self.env['sale.order.line']._fields

        # 3. حل مشكلة الـ N+1 Queries بجلب البيانات مسبقاً (Prefetching)
        orders.mapped('order_line.product_id.standard_price')
        if has_purchase_price:
            orders.mapped('order_line.purchase_price')
        orders.mapped('order_line.product_id.categ_id')

        for order in orders:
            for line in order.order_line:

                if line.display_type:
                    continue

                unit_cost = line.purchase_price if has_purchase_price else line.product_id.standard_price
                total_cost += (unit_cost * line.product_uom_qty)

                if line.discount > 0:
                    original_price = line.price_unit * line.product_uom_qty
                    total_discount += original_price * (line.discount / 100)

        gross_profit = total_revenue - total_cost
        profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

        # 3. To Invoice Amount
        orders_to_invoice = orders.filtered(lambda o: o.invoice_status == 'to invoice')
        total_invoiced = sum(orders_to_invoice.mapped('amount_untaxed'))

        # 4. Outstanding Debt
        unpaid_domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                         ('payment_state', 'in', ['not_paid', 'partial'])]

        if company_id and company_id != 'all': unpaid_domain.append(('company_id', '=', int(company_id)))
        if user_id and user_id != 'all': unpaid_domain.append(('invoice_user_id', '=', int(user_id)))
        if team_id and team_id != 'all': unpaid_domain.append(('team_id', '=', int(team_id)))

        unpaid_agg = self.env['account.move'].read_group(
            unpaid_domain, ['amount_residual:sum'], []
        )
        outstanding_receivables = unpaid_agg[0].get('amount_residual', 0) if unpaid_agg else 0

        to_invoice_domain = expression.AND([nav_domain, [('invoice_status', '=', 'to invoice')]])

        # 6. Chart Logic
        customer_sales, product_sales, daily_sales, salesperson_sales, category_sales, team_sales = {}, {}, {}, {}, {}, {}

        current_day = previous_date_end + timedelta(days=1)
        while current_day <= current_date_end:
            daily_sales[current_day.strftime('%Y-%m-%d')] = 0
            current_day += timedelta(days=1)

        for order in orders:
            c_name = order.partner_id.name or 'Unknown'
            customer_sales[c_name] = customer_sales.get(c_name, 0) + order.amount_untaxed

            day_key = order.date_order.strftime('%Y-%m-%d')
            if day_key in daily_sales:
                daily_sales[day_key] += order.amount_untaxed

            u_name = order.user_id.name or 'Unknown'
            salesperson_sales[u_name] = salesperson_sales.get(u_name, 0) + order.amount_untaxed

            t_name = order.team_id.name or 'No Team'
            team_sales[t_name] = team_sales.get(t_name, 0) + order.amount_untaxed

            for line in order.order_line:
                if line.display_type:
                    continue

                p_name = line.product_id.name or 'Unknown'
                product_sales[p_name] = product_sales.get(p_name, 0) + line.product_uom_qty
                raw_cat_name = line.product_id.categ_id.complete_name or 'Uncategorized'
                if raw_cat_name.startswith('All / '):
                    cat_name = raw_cat_name.replace('All / ', '', 1)
                else:
                    cat_name = raw_cat_name
                category_sales[cat_name] = category_sales.get(cat_name, 0) + line.price_subtotal

        sorted_customers = sorted(customer_sales.items(), key=lambda x: x[1], reverse=True)[:top_customers_limit]
        sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:top_products_limit]
        sorted_salespersons = sorted(salesperson_sales.items(), key=lambda x: x[1], reverse=True)[
            :top_salespeople_limit]
        sorted_categories = sorted(category_sales.items(), key=lambda x: x[1], reverse=True)[:top_categories_limit]
        sorted_teams = sorted(team_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        # 7. Dynamic Group By (WITH VALIDATION FIX)
        dynamic_chart_labels = []
        dynamic_chart_data = []
        if group_by_list:
            dynamic_chart_dict = {}
            for order in orders:
                label_parts = []
                for gb in group_by_list:

                    if gb not in self.ALLOWED_FIELDS:
                        continue
                    display_val = self._get_field_display_value(order, gb)
                    label_parts.append(str(display_val))

                if label_parts:
                    label = " / ".join(label_parts)
                    dynamic_chart_dict[label] = dynamic_chart_dict.get(label, 0) + order.amount_untaxed

            dynamic_chart_labels = list(dynamic_chart_dict.keys())
            dynamic_chart_data = [round(val, 2) for val in dynamic_chart_dict.values()]

        safe_nav_domain = self._serialize_domain(nav_domain)
        safe_to_invoice_domain = self._serialize_domain(to_invoice_domain)

        return {
            'total_revenue': round(total_revenue, 2), 'total_orders': total_orders, 'aov': round(aov, 2),
            'sales_growth': round(sales_growth, 2), 'gross_profit': round(gross_profit, 2),
            'profit_margin': round(profit_margin, 2), 'total_discount': round(total_discount, 2),
            'outstanding_receivables': round(outstanding_receivables, 2), 'total_invoiced': round(total_invoiced, 2),

            'customer_labels': [i[0] for i in sorted_customers], 'customer_data': [i[1] for i in sorted_customers],
            'product_labels': [i[0] for i in sorted_products], 'product_data': [i[1] for i in sorted_products],
            'trend_labels': list(daily_sales.keys()), 'trend_data': list(daily_sales.values()),
            'salesperson_labels': [i[0] for i in sorted_salespersons],
            'salesperson_data': [i[1] for i in sorted_salespersons],
            'category_labels': [i[0] for i in sorted_categories], 'category_data': [i[1] for i in sorted_categories],
            'team_labels': [i[0] for i in sorted_teams], 'team_data': [i[1] for i in sorted_teams],

            'dynamic_chart_labels': dynamic_chart_labels, 'dynamic_chart_data': dynamic_chart_data,
            'nav_domain': safe_nav_domain, 'to_invoice_domain': safe_to_invoice_domain
        }

    @api.model
    def export_custom_pivot_excel(self, **kwargs):
        # 6. إضافة الفحص لمنع الانهيار لو مكتبة xlsxwriter مش موجودة
        if not xlsxwriter:
            return {'error': 'مكتبة xlsxwriter غير مثبتة على السيرفر.'}

        date_from, date_to = kwargs.get('date_from'), kwargs.get('date_to')
        state, user_id, warehouse_id = kwargs.get('state'), kwargs.get('user_id'), kwargs.get('warehouse_id')
        team_id, category_id = kwargs.get('team_id'), kwargs.get('category_id')
        country_id, company_id = kwargs.get('country_id'), kwargs.get('company_id')
        detailed_excel = kwargs.get('detailed_excel', False)

        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])

        and_tuples = []
        if date_from and date_to:
            and_tuples += [('date_order', '>=', f"{date_from} 00:00:00"),
                           ('date_order', '<=', f"{date_to} 23:59:59")]

        if warehouse_id and warehouse_id != 'all': and_tuples.append(('warehouse_id', '=', int(warehouse_id)))
        if user_id and user_id != 'all': and_tuples.append(('user_id', '=', int(user_id)))
        if team_id and team_id != 'all': and_tuples.append(('team_id', '=', int(team_id)))
        if category_id and category_id != 'all': and_tuples.append(
            ('order_line.product_id.categ_id', 'child_of', int(category_id)))
        if country_id and country_id != 'all': and_tuples.append(('partner_id.country_id', '=', int(country_id)))
        if company_id and company_id != 'all': and_tuples.append(('company_id', '=', int(company_id)))

        if active_filters.get('my_orders'): and_tuples.append(('user_id', '=', self.env.uid))
        if active_filters.get('to_invoice'): and_tuples.append(('invoice_status', '=', 'to invoice'))

        # SQL State Filter
        if active_filters.get('quotations') or state == 'quotation':
            and_tuples.append(('state', 'in', ['draft', 'sent']))
        elif active_filters.get('sales_orders') or state == 'sale':
            and_tuples.append(('state', 'in', ['sale', 'done']))
        else:
            and_tuples.append(('state', '!=', 'cancel'))

        valid_operators = self.ALLOWED_OPERATORS
        valid_fields = self.ALLOWED_FIELDS

        if custom_domain_list:
            for c_filter in custom_domain_list:
                f_name = c_filter.get('field')
                op = c_filter.get('operator')
                val = c_filter.get('value')
                f_type = c_filter.get('type')

                if f_name not in valid_fields or op not in valid_operators:
                    continue

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
            search_domain = ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)

        domain = expression.AND(final_domain_list) if final_domain_list else []
        orders = self.env['sale.order'].search(domain)

        export_group = kwargs.get('export_group', 'partner_id')
        export_measures = kwargs.get('export_measures', ['revenue'])

        has_purchase_price = 'purchase_price' in self.env['sale.order.line']._fields

        # Prefetching
        orders.mapped('order_line.product_id.standard_price')
        if has_purchase_price:
            orders.mapped('order_line.purchase_price')
        orders.mapped('order_line.product_id.categ_id')

        pivot_data = {}
        for order in orders:
            key = 'Unknown'
            if export_group == 'partner_id':
                key = order.partner_id.name or 'Unknown'
            elif export_group == 'user_id':
                key = order.user_id.name or 'Unknown'
            elif export_group == 'date:month':
                key = order.date_order.strftime('%B %Y') if order.date_order else 'Unknown'

            if export_group in ['product_id', 'categ_id']:
                for line in order.order_line:
                    if line.display_type:
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
                        pivot_data[line_key] = {'revenue': 0, 'qty': 0, 'profit': 0, 'discount': 0, 'orders': set(),
                                                'lines': []}

                    unit_cost = line.purchase_price if has_purchase_price else line.product_id.standard_price

                    pivot_data[line_key]['revenue'] += line.price_subtotal
                    pivot_data[line_key]['qty'] += line.product_uom_qty
                    profit = line.price_subtotal - (unit_cost * line.product_uom_qty)
                    pivot_data[line_key]['profit'] += profit
                    disc = (line.price_unit * line.product_uom_qty) * (line.discount / 100) if line.discount else 0
                    pivot_data[line_key]['discount'] += disc
                    pivot_data[line_key]['orders'].add(order.id)
                    if detailed_excel: pivot_data[line_key]['lines'].append(
                        {'name': order.name, 'revenue': line.price_subtotal, 'qty': line.product_uom_qty,
                         'profit': profit, 'discount': disc, 'date': str(order.date_order.date())})
            else:
                if key not in pivot_data: pivot_data[key] = {'revenue': 0, 'qty': 0, 'profit': 0, 'discount': 0,
                                                             'orders': set(), 'lines': []}
                pivot_data[key]['revenue'] += order.amount_untaxed
                pivot_data[key]['orders'].add(order.id)
                order_profit, order_disc, order_qty = 0, 0, 0
                for line in order.order_line:
                    if line.display_type:
                        continue

                    unit_cost = line.purchase_price if has_purchase_price else line.product_id.standard_price
                    order_qty += line.product_uom_qty
                    order_profit += (line.price_subtotal - (unit_cost * line.product_uom_qty))
                    if line.discount > 0: order_disc += (line.price_unit * line.product_uom_qty) * (line.discount / 100)
                pivot_data[key]['qty'] += order_qty
                pivot_data[key]['profit'] += order_profit
                pivot_data[key]['discount'] += order_disc
                if detailed_excel: pivot_data[key]['lines'].append(
                    {'name': order.name, 'revenue': order.amount_untaxed, 'qty': order_qty, 'profit': order_profit,
                     'discount': order_disc, 'date': str(order.date_order.date())})

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Pivot Analysis')
        if detailed_excel: sheet.outline_settings(symbols_below=False)

        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_format = workbook.add_format({'border': 1, 'align': 'center'})
        pct_format = workbook.add_format({'num_format': '0.00"%"', 'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f8fafc'})
        detail_text_format = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})
        detail_money_format = workbook.add_format(
            {'num_format': '#,##0.00', 'border': 1, 'font_color': '#475569', 'bg_color': '#ffffff'})

        group_titles = {'partner_id': 'Customer', 'product_id': 'Product', 'categ_id': 'Category',
                        'user_id': 'Salesperson', 'date:month': 'Month'}
        headers = [group_titles.get(export_group, 'Group')]

        if 'revenue' in export_measures: headers.append('Total Revenue (EGP)')
        if 'qty' in export_measures: headers.append('Quantity Sold')
        if 'profit' in export_measures: headers.append('Gross Profit')
        if 'discount' in export_measures: headers.append('Total Discounts')
        if 'order_count' in export_measures: headers.append('Orders Count')
        if 'aov' in export_measures: headers.append('Avg Order Value')
        if 'margin_pct' in export_measures: headers.append('Profit Margin (%)')

        for col_num, header in enumerate(headers):
            sheet.write(0, col_num, header, header_format)
            sheet.set_column(col_num, col_num, 35 if col_num == 0 else 18)

        row = 1
        for k, data in sorted(pivot_data.items(), key=lambda x: x[1]['revenue'], reverse=True):
            sheet.write(row, 0, str(k), text_format)
            col = 1
            if 'revenue' in export_measures: sheet.write(row, col, data['revenue'], money_format); col += 1
            if 'qty' in export_measures: sheet.write(row, col, data['qty'], num_format); col += 1
            if 'profit' in export_measures: sheet.write(row, col, data['profit'], money_format); col += 1
            if 'discount' in export_measures: sheet.write(row, col, data['discount'], money_format); col += 1
            if 'order_count' in export_measures: sheet.write(row, col, len(data['orders']), num_format); col += 1
            if 'aov' in export_measures:
                aov_val = data['revenue'] / len(data['orders']) if len(data['orders']) > 0 else 0
                sheet.write(row, col, aov_val, money_format);
                col += 1
            if 'margin_pct' in export_measures:
                margin_val = (data['profit'] / data['revenue'] * 100) if data['revenue'] > 0 else 0
                sheet.write(row, col, margin_val, pct_format);
                col += 1

            if detailed_excel and 'lines' in data:
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0, f"   ↳ {line['name']} ({line['date']})", detail_text_format)
                    col = 1
                    if 'revenue' in export_measures: sheet.write(row, col, line['revenue'],
                                                                 detail_money_format); col += 1
                    if 'qty' in export_measures: sheet.write(row, col, line['qty'], detail_money_format); col += 1
                    if 'profit' in export_measures: sheet.write(row, col, line['profit'], detail_money_format); col += 1
                    if 'discount' in export_measures: sheet.write(row, col, line['discount'],
                                                                  detail_money_format); col += 1
                    if 'order_count' in export_measures: sheet.write(row, col, 1, detail_money_format); col += 1
                    if 'aov' in export_measures: sheet.write(row, col, line['revenue'], detail_money_format); col += 1
                    if 'margin_pct' in export_measures:
                        m_val = (line['profit'] / line['revenue'] * 100) if line['revenue'] > 0 else 0
                        sheet.write(row, col, m_val, detail_money_format);
                        col += 1
                    sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                    row += 1
            else:
                row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'Sales_Export_{fields.Date.today()}.xlsx', 'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id