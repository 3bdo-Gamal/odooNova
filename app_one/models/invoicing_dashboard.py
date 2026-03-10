from odoo import models, fields, api
from datetime import datetime, timedelta, date


class InvoicingDashboard(models.Model):
    _name = 'wb.invoicing.dashboard'
    _description = 'Invoicing KPI Dashboard'

    @api.model
    def get_filter_options(self):
        # فلاتر تناسب الحسابات
        journals = self.env['account.journal'].search_read([('type', '=', 'sale')], ['id', 'name'])
        users = self.env['res.users'].search_read([('share', '=', False)], ['id', 'name'])
        companies = self.env['res.company'].search_read([], ['id', 'name'])

        return {
            'journals': journals, 'users': users, 'companies': companies
        }

    @api.model
    def get_invoicing_dashboard_data(self, **kwargs):
        period = kwargs.get('period', 30)
        date_from = kwargs.get('date_from', False)
        date_to = kwargs.get('date_to', False)
        journal_id = kwargs.get('journal_id', 'all')
        user_id = kwargs.get('user_id', 'all')
        company_id = kwargs.get('company_id', 'all')
        payment_state = kwargs.get('payment_state', 'all')

        native_domain = kwargs.get('native_domain', [])

        # 1. تظبيط التواريخ وحساب عدد الأيام (مهم جداً عشان الـ DSO)
        delta_days = 30
        if date_from and date_to:
            current_date_start = datetime.strptime(date_from, '%Y-%m-%d').date()
            current_date_end = datetime.strptime(date_to, '%Y-%m-%d').date()
            if current_date_start > current_date_end:
                current_date_start, current_date_end = current_date_end, current_date_start
            delta_days = (current_date_end - current_date_start).days + 1
        else:
            period = int(period) if period and int(period) > 0 else 30
            delta_days = period
            current_date_end = date.today()
            current_date_start = current_date_end - timedelta(days=period)

        # بنفلتر فواتير العملاء المُرحلة بس
        base_domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', current_date_start),
            ('invoice_date', '<=', current_date_end)
        ]

        extra_domain = []
        if journal_id and journal_id != 'all': extra_domain.append(('journal_id', '=', int(journal_id)))
        if user_id and user_id != 'all': extra_domain.append(('invoice_user_id', '=', int(user_id)))
        if company_id and company_id != 'all': extra_domain.append(('company_id', '=', int(company_id)))
        if payment_state and payment_state != 'all': extra_domain.append(('payment_state', '=', payment_state))

        if native_domain: extra_domain += native_domain

        invoices = self.env['account.move'].search(base_domain + extra_domain)

        # حساب الـ KPIs
        total_invoiced_amount = sum(invoices.mapped('amount_total'))
        total_invoices_count = len(invoices)

        # Accounts Receivable (Unpaid Amount)
        unpaid_amount = sum(invoices.mapped('amount_residual'))

        # Cash Collected (Paid Amount)
        cash_collected = total_invoiced_amount - unpaid_amount

        # Paid & Unpaid Ratios (مبنية على المبالغ عشان تكون أدق مالياً)
        paid_ratio = (cash_collected / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0
        unpaid_ratio = (unpaid_amount / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        # Overdue Amount
        today = date.today()
        overdue_invoices = invoices.filtered(
            lambda inv: inv.invoice_date_due and inv.invoice_date_due < today and inv.amount_residual > 0)
        overdue_amount = sum(overdue_invoices.mapped('amount_residual'))
        overdue_rate = (overdue_amount / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        # DSO (Days Sales Outstanding) = (AR / Total Credit Sales) * Number of Days
        dso = (unpaid_amount / total_invoiced_amount * delta_days) if total_invoiced_amount > 0 else 0

        # Bad Debt % (قيمة افتراضية مجهزة للربط مع قيود التسوية)
        written_off_amount = 0.0
        bad_debt_pct = (written_off_amount / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        # داتا للرسومات البيانية
        daily_invoiced = {}
        daily_collected = {}
        customer_ar = {}

        for inv in invoices:
            day_key = inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else 'Unknown'
            daily_invoiced[day_key] = daily_invoiced.get(day_key, 0) + inv.amount_total
            daily_collected[day_key] = daily_collected.get(day_key, 0) + (inv.amount_total - inv.amount_residual)

            if inv.amount_residual > 0:
                c_name = inv.partner_id.name or 'Unknown'
                customer_ar[c_name] = customer_ar.get(c_name, 0) + inv.amount_residual

        # ترتيب التواريخ وأكبر العملاء المديونين
        sorted_dates = sorted(list(daily_invoiced.keys()))
        trend_invoiced_data = [daily_invoiced[d] for d in sorted_dates]
        trend_collected_data = [daily_collected[d] for d in sorted_dates]

        sorted_customers = sorted(customer_ar.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            'total_invoiced_amount': round(total_invoiced_amount, 2),
            'cash_collected': round(cash_collected, 2),
            'unpaid_amount': round(unpaid_amount, 2),
            'paid_ratio': round(paid_ratio, 1),
            'unpaid_ratio': round(unpaid_ratio, 1),
            'overdue_amount': round(overdue_amount, 2),
            'overdue_rate': round(overdue_rate, 1),
            'dso': round(dso, 1),
            'bad_debt_pct': round(bad_debt_pct, 2),

            'trend_labels': sorted_dates,
            'trend_invoiced_data': trend_invoiced_data,
            'trend_collected_data': trend_collected_data,

            'customer_labels': [i[0] for i in sorted_customers],
            'customer_data': [i[1] for i in sorted_customers],

            'nav_domain': base_domain + extra_domain,
        }