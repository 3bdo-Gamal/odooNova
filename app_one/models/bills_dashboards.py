from odoo import models, fields, api
from datetime import date, timedelta, datetime


class PurchaseBillsDashboard(models.Model):
    _name = 'wb.purchase.bills.dashboard'
    _description = 'Purchase Bills Dashboard Logic'
    _auto = False

    @api.model
    def get_kpi_data(self, date_filter='this_year'):
        # 1. تحديد الـ Domain حسب التاريخ
        domain = [('move_type', '=', 'in_invoice'), ('state', '=', 'posted')]
        today = date.today()

        if date_filter == 'this_week':
            start_date = today - timedelta(days=today.weekday())
            domain += [('invoice_date', '>=', start_date)]
        elif date_filter == 'last_week':
            end_date = today - timedelta(days=today.weekday() + 1)
            start_date = end_date - timedelta(days=6)
            domain += [('invoice_date', '>=', start_date), ('invoice_date', '<=', end_date)]
        elif date_filter == 'this_month':
            domain += [('invoice_date', '>=', today.replace(day=1))]
        elif date_filter == 'last_month':
            last_day_prev_month = today.replace(day=1) - timedelta(days=1)
            start_date = last_day_prev_month.replace(day=1)
            domain += [('invoice_date', '>=', start_date), ('invoice_date', '<=', last_day_prev_month)]
        elif date_filter == 'last_3_months':
            start_date = today - timedelta(days=90)
            domain += [('invoice_date', '>=', start_date)]
        elif date_filter == 'last_6_months':
            start_date = today - timedelta(days=180)
            domain += [('invoice_date', '>=', start_date)]
        elif date_filter == 'this_year':
            domain += [('invoice_date', '>=', today.replace(month=1, day=1))]
        elif date_filter == 'last_year':
            start_date = date(today.year - 1, 1, 1)
            end_date = date(today.year - 1, 12, 31)
            domain += [('invoice_date', '>=', start_date), ('invoice_date', '<=', end_date)]

        # استخدام self.env بدلاً من request.env
        AccountMove = self.env['account.move']

        # --- (نسخ نفس لوجيك الحسابات القديم) ---

        # 1. Cards Data
        all_bills = AccountMove.search(domain)
        upcoming_payables = sum(all_bills.filtered(
            lambda b: b.payment_state == 'not_paid' and b.invoice_date_due and b.invoice_date_due <= today + timedelta(
                days=30)
        ).mapped('amount_residual'))

        # DPO Calculation
        paid_bills = all_bills.filtered(lambda b: b.payment_state == 'paid')
        total_days = 0
        count_paid = 0
        for bill in paid_bills:
            payment_date = bill.payment_id.date if bill.payment_id else bill.invoice_date
            # Note: This is simplified; specific payment logic might vary based on your data
            if not payment_date:
                # محاولة جلب آخر تاريخ سداد من الـ widgets
                payment_date = bill.invoice_date  # Fallback

            if bill.invoice_date and payment_date:
                delta = (payment_date - bill.invoice_date).days
                total_days += delta
                count_paid += 1

        avg_dpo = round(total_days / count_paid) if count_paid > 0 else 0

        # Late Bills
        late_bills_count = len(all_bills.filtered(
            lambda b: b.payment_state == 'not_paid' and b.invoice_date_due and b.invoice_date_due < today
        ))
        total_count = len(all_bills)
        late_bills_ratio = round((late_bills_count / total_count) * 100) if total_count > 0 else 0

        # No-PO Ratio
        no_po_count = len(all_bills.filtered(lambda b: not b.invoice_origin))  # Simplified check
        wo_po_ratio = round((no_po_count / total_count) * 100) if total_count > 0 else 0

        # 2. Charts Data (Spend Trend)
        spend_trend_data = AccountMove.read_group(
            domain,
            ['amount_total:sum'],
            ['invoice_date:month']
        )
        trend_labels = [d['invoice_date:month'] for d in spend_trend_data]
        trend_values = [d['amount_total'] for d in spend_trend_data]

        # 3. Charts Data (Top Vendors)
        top_vendors_data = AccountMove.read_group(
            domain,
            ['amount_total:sum'],
            ['partner_id'],
            orderby='amount_total DESC',
            limit=10
        )
        vendor_labels = [d['partner_id'][1] if d['partner_id'] else 'Unknown' for d in top_vendors_data]
        vendor_values = [d['amount_total'] for d in top_vendors_data]

        return {
            'cards': {
                'upcoming_payables': f"{upcoming_payables:,.0f}",
                'avg_dpo': avg_dpo,
                'late_bills_ratio': late_bills_ratio,
                'wo_po_ratio': wo_po_ratio,
            },
            'charts': {
                'spend_trend': {'labels': trend_labels, 'data': trend_values},
                'top_vendors': {'labels': vendor_labels, 'data': vendor_values},
            }
        }