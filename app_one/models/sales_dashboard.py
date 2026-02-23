from odoo import models, fields, api
from datetime import datetime, timedelta


class SalesDashboard(models.Model):
    _name = 'wb.sales.dashboard'
    _description = 'Sales KPI Dashboard'

    @api.model
    def get_sales_dashboard_data(self, period=7, customer_type='all'):
        # 1. Date Configuration
        period = int(period) if int(period) > 0 else 7

        current_date_end = datetime.now()
        current_date_start = current_date_end - timedelta(days=period)
        previous_date_end = current_date_start - timedelta(seconds=1)
        previous_date_start = previous_date_end - timedelta(days=period)

        time_domain = [('date_order', '>=', current_date_start), ('date_order', '<=', current_date_end)]
        prev_time_domain = [('date_order', '>=', previous_date_start), ('date_order', '<=', previous_date_end)]

        # 2. Customer Type Filtering (ID Method)
        wholesale_partners = self.env['res.partner'].search([('category_id.name', '=', 'Wholesale')])

        type_domain = []
        if customer_type == 'wholesale':
            type_domain = [('partner_id', 'in', wholesale_partners.ids)]
        elif customer_type == 'retail':
            type_domain = [('partner_id', 'not in', wholesale_partners.ids)]

        # 3. Fetch Sales Orders & Core KPIs
        orders = self.env['sale.order'].search([('state', 'in', ['sale', 'done'])] + time_domain + type_domain)

        total_revenue = sum(orders.mapped('amount_total'))
        total_orders = len(orders)
        aov = total_revenue / total_orders if total_orders > 0 else 0

        # 4. Sales Growth Calculation
        prev_orders = self.env['sale.order'].search(
            [('state', 'in', ['sale', 'done'])] + prev_time_domain + type_domain)
        prev_revenue = sum(prev_orders.mapped('amount_total'))
        sales_growth = ((total_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0

        # 5. Financials: Cost, Discount & Profit
        total_cost = 0
        total_discount = 0

        for order in orders:
            for line in order.order_line:
                total_cost += (line.product_id.standard_price * line.product_uom_qty)
                if line.discount > 0:
                    original_price = line.price_unit * line.product_uom_qty
                    discount_amount = original_price * (line.discount / 100)
                    total_discount += discount_amount

        gross_profit = total_revenue - total_cost
        profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

        # 6. Outstanding Receivables (Unpaid Invoices)
        unpaid_invoices = self.env['account.move'].search([
                                                              ('move_type', '=', 'out_invoice'),
                                                              ('state', '=', 'posted'),
                                                              ('payment_state', 'in', ['not_paid', 'partial']),
                                                              ('invoice_date', '>=', current_date_start)
                                                          ] + type_domain)

        outstanding_receivables = sum(unpaid_invoices.mapped('amount_residual'))

        # 7. Chart Data Aggregation
        # Top 5 Customers
        customer_sales = {}
        for order in orders:
            name = order.partner_id.name or 'Unknown'
            customer_sales[name] = customer_sales.get(name, 0) + order.amount_total
        sorted_customers = sorted(customer_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        # Top 5 Products
        product_sales = {}
        for order in orders:
            for line in order.order_line:
                p_name = line.product_id.name or 'Unknown'
                product_sales[p_name] = product_sales.get(p_name, 0) + line.product_uom_qty
        sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        # Daily Trend
        daily_sales = {}
        current_day = previous_date_end + timedelta(days=1)
        while current_day <= current_date_end:
            day_str = current_day.strftime('%Y-%m-%d')
            daily_sales[day_str] = 0
            current_day += timedelta(days=1)

        for order in orders:
            day_key = order.date_order.strftime('%Y-%m-%d')
            if day_key in daily_sales:
                daily_sales[day_key] += order.amount_total

        # Top 5 Salespeople
        salesperson_sales = {}
        for order in orders:
            user_name = order.user_id.name or 'Unknown'
            salesperson_sales[user_name] = salesperson_sales.get(user_name, 0) + order.amount_total
        sorted_salespersons = sorted(salesperson_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        # Top 5 Categories
        category_sales = {}
        for order in orders:
            for line in order.order_line:
                cat_name = line.product_id.categ_id.name or 'Uncategorized'
                category_sales[cat_name] = category_sales.get(cat_name, 0) + line.price_subtotal
        sorted_categories = sorted(category_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        # 8. Return Dashboard Data
        return {
            'total_revenue': round(total_revenue, 2),
            'total_orders': total_orders,
            'aov': round(aov, 2),
            'sales_growth': round(sales_growth, 2),
            'gross_profit': round(gross_profit, 2),
            'profit_margin': round(profit_margin, 2),
            'total_discount': round(total_discount, 2),
            'outstanding_receivables': round(outstanding_receivables, 2),

            'customer_labels': [item[0] for item in sorted_customers],
            'customer_data': [item[1] for item in sorted_customers],
            'product_labels': [item[0] for item in sorted_products],
            'product_data': [item[1] for item in sorted_products],
            'trend_labels': list(daily_sales.keys()),
            'trend_data': list(daily_sales.values()),
            'salesperson_labels': [item[0] for item in sorted_salespersons],
            'salesperson_data': [item[1] for item in sorted_salespersons],
            'category_labels': [item[0] for item in sorted_categories],
            'category_data': [item[1] for item in sorted_categories],
        }