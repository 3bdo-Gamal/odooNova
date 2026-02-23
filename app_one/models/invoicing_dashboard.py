from odoo import models, api
from datetime import datetime, timedelta

class InvoicingDashboard(models.Model):
    _name = 'wb.invoicing.dashboard'
    _description = 'Invoicing KPI Dashboard'

    @api.model
    def get_invoicing_data(self, period=30):
        # 1. Period configuration (supports up to 365 days)
        try:
            period = int(period)
        except (ValueError, TypeError):
            period = 30

        current_date = datetime.now().date()
        start_date = current_date - timedelta(days=period)

        # 2. Fetch posted customer invoices within the selected period
        invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', start_date)
        ])

        # 3. Core KPI Calculations
        total_invoiced = sum(invoices.mapped('amount_total'))
        total_count = len(invoices)

        # Filter paid vs unpaid invoices
        paid_invoices = invoices.filtered(lambda i: i.payment_state in ['paid', 'in_payment'])
        unpaid_invoices = invoices.filtered(lambda i: i.payment_state in ['not_paid', 'partial'])

        # Calculate ratios
        paid_ratio = (len(paid_invoices) / total_count * 100) if total_count > 0 else 0
        unpaid_ratio = (len(unpaid_invoices) / total_count * 100) if total_count > 0 else 0

        # 4. Financial Status (Cash vs Debt)
        residual_amount = sum(invoices.mapped('amount_residual'))
        cash_collected = total_invoiced - residual_amount

        # Calculate overdue amounts based on due date
        overdue_invoices = unpaid_invoices.filtered(
            lambda i: i.invoice_date_due and i.invoice_date_due < current_date
        )
        overdue_amount = sum(overdue_invoices.mapped('amount_residual'))

        # 5. Daily Collection Trend for Chart.js
        daily_collection = {}
        # Initialize the date structure for the selected period
        for i in range(period):
            date_str = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_collection[date_str] = 0

        # Aggregate collected amounts by invoice date
        for inv in invoices:
            collected_from_inv = inv.amount_total - inv.amount_residual
            if collected_from_inv > 0:
                date_key = inv.invoice_date.strftime('%Y-%m-%d')
                if date_key in daily_collection:
                    daily_collection[date_key] += collected_from_inv

        # 6. Return data to JavaScript Frontend
        return {
            'total_invoiced': round(total_invoiced, 2),
            'paid_ratio': round(paid_ratio, 1),
            'unpaid_ratio': round(unpaid_ratio, 1),
            'overdue_amount': round(overdue_amount, 2),
            'cash_collected': round(cash_collected, 2),
            # DSO Equation: (Total Receivables / Total Sales) * Days in Period
            'dso': round((residual_amount / total_invoiced * period), 1) if total_invoiced > 0 else 0,
            'bad_debt_pct': 0,  # Placeholder for future implementation
            'trend_labels': list(daily_collection.keys()),
            'trend_data': list(daily_collection.values()),
        }