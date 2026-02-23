from odoo import models, api
from datetime import datetime, timedelta


class PosDashboard(models.Model):
    _name = 'wb.pos.dashboard'
    _description = 'POS KPI Dashboard'

    @api.model
    def get_pos_dashboard_data(self, period=7):
        # 1. Period configuration
        try:
            period = int(period)
        except (ValueError, TypeError):
            period = 7

        current_date_end = datetime.now()
        current_date_start = current_date_end - timedelta(days=period)
        domain = [('date_order', '>=', current_date_start), ('date_order', '<=', current_date_end)]

        # 2. Safety check: Ensure the Point of Sale module is installed
        if 'pos.order' not in self.env:
            return {}

        # 3. Fetch POS orders within the defined domain
        orders = self.env['pos.order'].search(domain)

        # 4. Total POS Revenue & Orders Count
        pos_revenue = sum(orders.mapped('amount_total'))
        pos_orders_count = len(orders)

        # 5. Payment Ratios (Cash vs Card)
        payments = self.env['pos.payment'].search([('pos_order_id', 'in', orders.ids)])

        # Calculate cash payments based on journal type or method name
        cash_payments = sum(p.amount for p in payments if
                            p.payment_method_id.journal_id.type == 'cash' or
                            'cash' in (p.payment_method_id.name or '').lower())

        # Calculate card/bank payments
        card_payments = sum(p.amount for p in payments if
                            p.payment_method_id.journal_id.type == 'bank' or
                            'bank' in (p.payment_method_id.name or '').lower() or
                            'card' in (p.payment_method_id.name or '').lower())

        cash_ratio = (cash_payments / pos_revenue * 100) if pos_revenue > 0 else 0
        card_ratio = (card_payments / pos_revenue * 100) if pos_revenue > 0 else 0

        # 6. POS Refund Rate calculation
        refunded_amount = sum(abs(o.amount_total) for o in orders if o.amount_total < 0)
        pos_refund_rate = (refunded_amount / pos_revenue * 100) if pos_revenue > 0 else 0

        # 7. Discount percentage based on Gross Sales
        total_discount = sum(
            (line.price_unit * line.qty) * (line.discount / 100)
            for order in orders for line in order.lines if line.discount > 0
        )
        gross_sales = pos_revenue + total_discount
        discount_pct = (total_discount / gross_sales * 100) if gross_sales > 0 else 0

        # 8. Revenue per Hour for Heatmap/Trend Chart
        hourly_revenue = {str(i): 0 for i in range(24)}
        for order in orders:
            if order.date_order:
                # Group sales by the hour of the order
                hour = str(order.date_order.hour)
                hourly_revenue[hour] += order.amount_total

        hours_labels = [f"{i}:00" for i in range(24)]
        hours_data = [hourly_revenue[str(i)] for i in range(24)]

        # 9. Return processed data to Frontend (Owl JS)
        return {
            'pos_revenue': round(pos_revenue, 2),
            'pos_orders_count': pos_orders_count,
            'cash_ratio': round(cash_ratio, 1),
            'card_ratio': round(card_ratio, 1),
            'pos_refund_rate': round(pos_refund_rate, 1),
            'discount_pct': round(discount_pct, 1),
            'hours_labels': hours_labels,
            'hours_data': hours_data,
        }