from odoo import models, fields, api
from datetime import datetime, timedelta
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class SalesDashboard(models.Model):
    _name = 'wb.sales.dashboard'
    _description = 'Sales KPI Dashboard'

    @api.model
    def get_filter_options(self):
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        users = self.env['res.users'].search_read([('share', '=', False)], ['id', 'name'])
        teams = self.env['crm.team'].search_read([], ['id', 'name'])
        categories = self.env['product.category'].search_read([], ['id', 'name'])
        partners = self.env['res.partner'].search_read([('customer_rank', '>', 0)], ['id', 'name'], limit=100)

        return {
            'warehouses': warehouses,
            'users': users,
            'teams': teams,
            'categories': categories,
            'partners': partners,
        }

    @api.model
    def get_sales_dashboard_data(self, **kwargs):
        period = kwargs.get('period', 7)
        date_from = kwargs.get('date_from', False)
        date_to = kwargs.get('date_to', False)
        warehouse_id = kwargs.get('warehouse_id', 'all')
        user_id = kwargs.get('user_id', 'all')
        state = kwargs.get('state', 'sale')
        team_id = kwargs.get('team_id', 'all')
        category_id = kwargs.get('category_id', 'all')
        partner_id = kwargs.get('partner_id', 'all')

        if date_from and date_to:
            current_date_start = datetime.strptime(date_from, '%Y-%m-%d')
            current_date_end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            if current_date_start > current_date_end:
                current_date_start, current_date_end = current_date_end, current_date_start
                current_date_end = current_date_end.replace(hour=23, minute=59, second=59)
            delta_days = (current_date_end - current_date_start).days + 1
            previous_date_end = current_date_start - timedelta(seconds=1)
            previous_date_start = previous_date_end - timedelta(days=delta_days)
        else:
            period = int(period) if period and int(period) > 0 else 7
            current_date_end = datetime.now()
            current_date_start = current_date_end - timedelta(days=period)
            previous_date_end = current_date_start - timedelta(seconds=1)
            previous_date_start = previous_date_end - timedelta(days=period)

        time_domain = [('date_order', '>=', current_date_start), ('date_order', '<=', current_date_end)]
        prev_time_domain = [('date_order', '>=', previous_date_start), ('date_order', '<=', previous_date_end)]

        extra_domain = []
        if warehouse_id and warehouse_id != 'all': extra_domain.append(('warehouse_id', '=', int(warehouse_id)))
        if user_id and user_id != 'all': extra_domain.append(('user_id', '=', int(user_id)))
        if team_id and team_id != 'all': extra_domain.append(('team_id', '=', int(team_id)))
        if partner_id and partner_id != 'all': extra_domain.append(('partner_id', '=', int(partner_id)))
        if category_id and category_id != 'all': extra_domain.append(
            ('order_line.product_id.categ_id', 'child_of', int(category_id)))

        all_period_orders = self.env['sale.order'].search(time_domain + extra_domain)

        if state and state != 'all':
            if state == 'quotation':
                orders = all_period_orders.filtered(lambda o: o.state in ['draft', 'sent'])
            else:
                orders = all_period_orders.filtered(lambda o: o.state in ['sale', 'done'])
        else:
            orders = all_period_orders.filtered(lambda o: o.state != 'cancel')

        total_revenue = sum(orders.mapped('amount_total'))
        total_orders = len(orders)
        aov = total_revenue / total_orders if total_orders > 0 else 0

        prev_orders = self.env['sale.order'].search(prev_time_domain + extra_domain).filtered(
            lambda o: o.state in ['sale', 'done'])
        prev_revenue = sum(prev_orders.mapped('amount_total'))
        sales_growth = ((total_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0

        total_cost = 0
        total_discount = 0
        for order in orders:
            for line in order.order_line:
                total_cost += (line.product_id.standard_price * line.product_uom_qty)
                if line.discount > 0:
                    original_price = line.price_unit * line.product_uom_qty
                    total_discount += original_price * (line.discount / 100)

        gross_profit = total_revenue - total_cost
        profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

        unpaid_domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                         ('payment_state', 'in', ['not_paid', 'partial']), ('invoice_date', '>=', current_date_start)]
        if user_id and user_id != 'all':
            unpaid_domain.append(('invoice_user_id', '=', int(user_id)))
        outstanding_receivables = sum(self.env['account.move'].search(unpaid_domain).mapped('amount_residual'))

        # Win Rate
        total_quotes = len(all_period_orders)
        won_quotes = len(all_period_orders.filtered(lambda o: o.state in ['sale', 'done']))
        lost_quotes = total_quotes - won_quotes
        win_rate = (won_quotes / total_quotes * 100) if total_quotes > 0 else 0

        customer_sales, product_sales, daily_sales, salesperson_sales, category_sales = {}, {}, {}, {}, {}
        current_day = previous_date_end + timedelta(days=1)
        while current_day <= current_date_end:
            daily_sales[current_day.strftime('%Y-%m-%d')] = 0
            current_day += timedelta(days=1)

        for order in orders:
            c_name = order.partner_id.name or 'Unknown'
            customer_sales[c_name] = customer_sales.get(c_name, 0) + order.amount_total
            day_key = order.date_order.strftime('%Y-%m-%d')
            if day_key in daily_sales: daily_sales[day_key] += order.amount_total
            u_name = order.user_id.name or 'Unknown'
            salesperson_sales[u_name] = salesperson_sales.get(u_name, 0) + order.amount_total
            for line in order.order_line:
                p_name = line.product_id.name or 'Unknown'
                product_sales[p_name] = product_sales.get(p_name, 0) + line.product_uom_qty
                cat_name = line.product_id.categ_id.name or 'Uncategorized'
                category_sales[cat_name] = category_sales.get(cat_name, 0) + line.price_subtotal

        sorted_customers = sorted(customer_sales.items(), key=lambda x: x[1], reverse=True)[:5]
        sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
        sorted_salespersons = sorted(salesperson_sales.items(), key=lambda x: x[1], reverse=True)[:5]
        sorted_categories = sorted(category_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            'total_revenue': round(total_revenue, 2), 'total_orders': total_orders, 'aov': round(aov, 2),
            'sales_growth': round(sales_growth, 2), 'gross_profit': round(gross_profit, 2),
            'profit_margin': round(profit_margin, 2), 'total_discount': round(total_discount, 2),
            'outstanding_receivables': round(outstanding_receivables, 2),

            'win_rate': round(win_rate, 1),
            'won_quotes': won_quotes, 'lost_quotes': lost_quotes,

            'customer_labels': [i[0] for i in sorted_customers], 'customer_data': [i[1] for i in sorted_customers],
            'product_labels': [i[0] for i in sorted_products], 'product_data': [i[1] for i in sorted_products],
            'trend_labels': list(daily_sales.keys()), 'trend_data': list(daily_sales.values()),
            'salesperson_labels': [i[0] for i in sorted_salespersons],
            'salesperson_data': [i[1] for i in sorted_salespersons],
            'category_labels': [i[0] for i in sorted_categories], 'category_data': [i[1] for i in sorted_categories],
        }

    @api.model
    def export_custom_pivot_excel(self, **kwargs):
        date_from, date_to = kwargs.get('date_from'), kwargs.get('date_to')
        state, user_id, warehouse_id = kwargs.get('state'), kwargs.get('user_id'), kwargs.get('warehouse_id')
        team_id, category_id, partner_id = kwargs.get('team_id'), kwargs.get('category_id'), kwargs.get('partner_id')

        domain = []
        if date_from and date_to:
            domain += [('date_order', '>=', f"{date_from} 00:00:00"), ('date_order', '<=', f"{date_to} 23:59:59")]
        if warehouse_id and warehouse_id != 'all': domain.append(('warehouse_id', '=', int(warehouse_id)))
        if user_id and user_id != 'all': domain.append(('user_id', '=', int(user_id)))
        if team_id and team_id != 'all': domain.append(('team_id', '=', int(team_id)))
        if partner_id and partner_id != 'all': domain.append(('partner_id', '=', int(partner_id)))
        if category_id and category_id != 'all': domain.append(
            ('order_line.product_id.categ_id', 'child_of', int(category_id)))

        orders = self.env['sale.order'].search(domain)
        if state and state != 'all':
            orders = orders.filtered(
                lambda o: o.state in (['draft', 'sent'] if state == 'quotation' else ['sale', 'done']))
        else:
            orders = orders.filtered(lambda o: o.state != 'cancel')

        export_group = kwargs.get('export_group', 'partner_id')
        export_measures = kwargs.get('export_measures', ['revenue'])

        pivot_data = {}

        for order in orders:
            if export_group == 'partner_id':
                key = order.partner_id.name or 'Unknown'
            elif export_group == 'user_id':
                key = order.user_id.name or 'Unknown'
            elif export_group == 'date:month':
                key = order.date_order.strftime('%B %Y') if order.date_order else 'Unknown'
            else:
                key = 'Unknown'

            if export_group in ['product_id', 'categ_id']:
                for line in order.order_line:
                    line_key = line.product_id.name if export_group == 'product_id' else line.product_id.categ_id.name
                    line_key = line_key or 'Unknown'
                    if line_key not in pivot_data:
                        pivot_data[line_key] = {'revenue': 0, 'qty': 0, 'profit': 0, 'discount': 0, 'orders': set()}

                    pivot_data[line_key]['revenue'] += line.price_subtotal
                    pivot_data[line_key]['qty'] += line.product_uom_qty
                    pivot_data[line_key]['profit'] += (
                                line.price_subtotal - (line.product_id.standard_price * line.product_uom_qty))
                    if line.discount > 0:
                        pivot_data[line_key]['discount'] += (line.price_unit * line.product_uom_qty) * (
                                    line.discount / 100)
                    pivot_data[line_key]['orders'].add(order.id)
            else:
                if key not in pivot_data:
                    pivot_data[key] = {'revenue': 0, 'qty': 0, 'profit': 0, 'discount': 0, 'orders': set()}
                pivot_data[key]['revenue'] += order.amount_total
                pivot_data[key]['orders'].add(order.id)
                for line in order.order_line:
                    pivot_data[key]['qty'] += line.product_uom_qty
                    pivot_data[key]['profit'] += (
                                line.price_subtotal - (line.product_id.standard_price * line.product_uom_qty))
                    if line.discount > 0:
                        pivot_data[key]['discount'] += (line.price_unit * line.product_uom_qty) * (line.discount / 100)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Pivot Analysis')

        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_format = workbook.add_format({'border': 1, 'align': 'center'})
        pct_format = workbook.add_format({'num_format': '0.00"%"', 'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1})

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
            sheet.set_column(col_num, col_num, 25 if col_num == 0 else 18)

        row = 1
        for k, data in sorted(pivot_data.items(), key=lambda x: x[1]['revenue'], reverse=True):
            sheet.write(row, 0, k, text_format)
            col = 1
            if 'revenue' in export_measures:
                sheet.write(row, col, data['revenue'], money_format)
                col += 1
            if 'qty' in export_measures:
                sheet.write(row, col, data['qty'], num_format)
                col += 1
            if 'profit' in export_measures:
                sheet.write(row, col, data['profit'], money_format)
                col += 1
            if 'discount' in export_measures:
                sheet.write(row, col, data['discount'], money_format)
                col += 1
            if 'order_count' in export_measures:
                sheet.write(row, col, len(data['orders']), num_format)
                col += 1
            if 'aov' in export_measures:
                aov_val = data['revenue'] / len(data['orders']) if len(data['orders']) > 0 else 0
                sheet.write(row, col, aov_val, money_format)
                col += 1
            if 'margin_pct' in export_measures:
                margin_val = (data['profit'] / data['revenue'] * 100) if data['revenue'] > 0 else 0
                sheet.write(row, col, margin_val, pct_format)
                col += 1
            row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'Sales_Pivot_Analysis_{fields.Date.today()}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id