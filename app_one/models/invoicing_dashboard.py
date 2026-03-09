from odoo import models, api, fields
from datetime import timedelta

class InvoicingDashboard(models.Model):
    _name = 'wb.invoicing.dashboard'
    _description = 'Invoicing KPI Dashboard'

    @api.model
    def get_invoicing_data(
        self,
        period=30,
        duration=None,
        date_from=None,
        date_to=None,
        invoice_filter=None
    ):

        today = fields.Date.today()


        # 1️⃣ Date Logic


        if date_from and date_to:
            start_date = fields.Date.from_string(date_from)
            end_date = fields.Date.from_string(date_to)

        elif duration == "today":
            start_date = today
            end_date = today

        elif duration == "week":
            start_date = today - timedelta(days=today.weekday())
            end_date = today

        elif duration == "month":
            start_date = today.replace(day=1)
            end_date = today

        else:
            try:
                period = int(period)
            except:
                period = 30
            start_date = today - timedelta(days=period)
            end_date = today

        days_count = (end_date - start_date).days + 1


        # 2️⃣ Base Domain


        domain = [
            ('move_type', '=', 'out_invoice'),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
        ]


        # 3️⃣ Invoice Filter


        if invoice_filter == "posted":
            domain.append(('state', '=', 'posted'))

        elif invoice_filter == "unposted":
            domain.append(('state', '=', 'draft'))

        elif invoice_filter == "paid":
            domain += [
                ('state', '=', 'posted'),
                ('payment_state', 'in', ['paid', 'in_payment'])
            ]

        elif invoice_filter == "unpaid":
            domain += [
                ('state', '=', 'posted'),
                ('payment_state', 'in', ['not_paid', 'partial'])
            ]

        invoices = self.env['account.move'].search(domain)


        # 4️⃣ KPI Calculations


        total_invoiced = sum(invoices.mapped('amount_total'))
        total_count = len(invoices)

        paid_invoices = invoices.filtered(
            lambda i: i.payment_state in ['paid', 'in_payment']
        )

        unpaid_invoices = invoices.filtered(
            lambda i: i.payment_state in ['not_paid', 'partial']
        )

        paid_ratio = (len(paid_invoices) / total_count * 100) if total_count else 0
        unpaid_ratio = (len(unpaid_invoices) / total_count * 100) if total_count else 0

        residual_amount = sum(invoices.mapped('amount_residual'))
        cash_collected = total_invoiced - residual_amount

        overdue_invoices = unpaid_invoices.filtered(
            lambda i: i.invoice_date_due and i.invoice_date_due < today
        )

        overdue_amount = sum(overdue_invoices.mapped('amount_residual'))


        # 5️⃣ Daily Trend


        daily_collection = {}

        for i in range(days_count):
            date_key = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_collection[date_key] = 0

        for inv in invoices:
            collected = inv.amount_total - inv.amount_residual
            if collected > 0 and inv.invoice_date:
                key = inv.invoice_date.strftime('%Y-%m-%d')
                if key in daily_collection:
                    daily_collection[key] += collected


        # 6️⃣ Return Data


        return {
            'total_invoiced': round(total_invoiced, 2),
            'paid_ratio': round(paid_ratio, 1),
            'unpaid_ratio': round(unpaid_ratio, 1),
            'overdue_amount': round(overdue_amount, 2),
            'cash_collected': round(cash_collected, 2),
            'dso': round((residual_amount / total_invoiced * days_count), 1) if total_invoiced else 0,
            'trend_labels': list(daily_collection.keys()),
            'trend_data': list(daily_collection.values()),
        }