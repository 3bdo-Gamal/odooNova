from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class PurchaseBillsDashboard(models.AbstractModel):
    _name = 'wb.purchase.bills.dashboard'
    _description = 'Purchase Bills Dashboard Logic'

    @api.model
    def get_dashboard_data(self, period='this_year'):
        today = fields.Date.context_today(self)
        start_date = today
        end_date = today

        # 1. Date Range Logic (الفلاتر الزمنية)
        if period == 'this_week':
            start_date = today - relativedelta(days=today.weekday())
        elif period == 'last_week':
            start_date = today - relativedelta(weeks=1, days=today.weekday())
            end_date = start_date + relativedelta(days=6)
        elif period == 'this_month':
            start_date = today.replace(day=1)
        elif period == 'last_month':
            start_date = (today - relativedelta(months=1)).replace(day=1)
            end_date = start_date + relativedelta(months=1, days=-1)
        elif period == 'last_3_months':
            start_date = today - relativedelta(months=3)
        elif period == 'last_6_months':
            start_date = today - relativedelta(months=6)
        elif period == 'this_year':
            start_date = today.replace(month=1, day=1)
        elif period == 'last_year':
            start_date = (today - relativedelta(years=1)).replace(month=1, day=1)
            end_date = start_date + relativedelta(years=1, days=-1)

        domain = [
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date)
        ]

        bills = self.env['account.move'].search(domain)

        # =========================================================
        # 2. KPIs Calculation (حساب الكروت العلوية)
        # =========================================================
        # Upcoming Payables
        upcoming_payables = sum(bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'] and b.invoice_date_due and b.invoice_date_due >= today).mapped('amount_residual'))

        # Average DPO
        dpo_list = bills.filtered(lambda b: b.payment_lead_time > 0).mapped('payment_lead_time')
        avg_dpo = round(sum(dpo_list) / len(dpo_list)) if dpo_list else 0

        # Late Bills Ratio
        unpaid_bills = bills.filtered(lambda b: b.payment_state in ['not_paid', 'partial'])
        late_bills = unpaid_bills.filtered(lambda b: b.overdue_days > 0)
        late_bills_ratio = round((len(late_bills) / len(unpaid_bills)) * 100) if unpaid_bills else 0

        # Maverick Spend Ratio
        bills_without_po = bills.filtered(lambda b: not b.purchase_id)
        wo_po_ratio = round((len(bills_without_po) / len(bills)) * 100) if bills else 0

        # حساب المبالغ المدفوعة وغير المدفوعة للرسم البياني (Status)
        paid_amount = sum(bills.filtered(lambda b: b.payment_state == 'paid').mapped('amount_total'))
        unpaid_total = sum(unpaid_bills.mapped('amount_residual'))

        # =========================================================
        # 3. Invoice Accuracy & Variances (الكميات والأسعار)
        # =========================================================
        bill_lines = self.env['account.move.line'].search([
            ('move_id', 'in', bills.ids),
            ('purchase_line_id', '!=', False),
            ('product_id', '!=', False)
        ])

        qty_pivot = []
        product_variances = {}
        overbilled_data = {}
        underbilled_data = {}

        for line in bill_lines:
            prod_name = line.product_id.name
            if line.qty_variance != 0:
                product_variances[prod_name] = product_variances.get(prod_name, 0) + line.qty_variance

            if line.price_variance > 0:
                overbilled_data[prod_name] = overbilled_data.get(prod_name, 0) + line.price_variance
            elif line.price_variance < 0:
                underbilled_data[prod_name] = underbilled_data.get(prod_name, 0) + abs(line.price_variance)

        for p, v in product_variances.items():
            qty_pivot.append({'product': p, 'qty_variance': round(v, 2)})

        qty_pivot = sorted(qty_pivot, key=lambda k: abs(k['qty_variance']), reverse=True)[:10]

        variance_products = list(set(list(overbilled_data.keys()) + list(underbilled_data.keys())))[:10]
        overbilled_arr = [round(overbilled_data.get(p, 0), 2) for p in variance_products]
        underbilled_arr = [round(underbilled_data.get(p, 0), 2) for p in variance_products]

        # =========================================================
        # 4. Standard Charts Queries
        # =========================================================
        trend_data = self.env['account.move'].read_group(domain, ['invoice_date', 'amount_total'], ['invoice_date:month'])
        trend_labels = [d['invoice_date:month'] for d in trend_data]
        trend_values = [d['amount_total'] for d in trend_data]

        vendor_data = self.env['account.move'].read_group(domain, ['partner_id', 'amount_total'], ['partner_id'], limit=10, orderby='amount_total desc')
        vendor_labels = [d['partner_id'][1] if d['partner_id'] else 'Unknown' for d in vendor_data]
        vendor_values = [d['amount_total'] for d in vendor_data]

        lead_data = self.env['account.move'].read_group(domain, ['partner_id', 'payment_lead_time'], ['partner_id'], limit=5)
        lead_labels = [d['partner_id'][1] if d['partner_id'] else 'Unknown' for d in lead_data]
        lead_values = [d['payment_lead_time'] for d in lead_data]

        return {
            'cards': {
                'upcoming_payables': f"${upcoming_payables:,.0f}",
                'avg_dpo': avg_dpo,
                'late_bills_ratio': late_bills_ratio,
                'wo_po_ratio': wo_po_ratio,
            },
            'tables': {
                'qty_variance_pivot': qty_pivot
            },
            'charts': {
                'status': {
                    'labels': ['Paid', 'Unpaid'],
                    'datasets': [{
                        'data': [paid_amount, unpaid_total],
                        'backgroundColor': ['#2ECC71', '#E74C3C']
                    }]
                },
                'trend': {
                    'labels': trend_labels,
                    'datasets': [{'label': 'Total Spend', 'data': trend_values, 'borderColor': '#3498DB', 'fill': False}]
                },
                'vendor': {
                    'labels': vendor_labels,
                    'datasets': [{'label': 'Amount', 'data': vendor_values, 'backgroundColor': '#27AE60'}]
                },
                'lead_time': {
                    'labels': lead_labels,
                    'datasets': [{'label': 'Avg Days', 'data': lead_values, 'backgroundColor': '#F39C12'}]
                },
                'price_var': {
                    'labels': variance_products,
                    'datasets': [
                        {'label': 'Overbilled', 'data': overbilled_arr, 'backgroundColor': '#E74C3C'},
                        {'label': 'Underbilled', 'data': underbilled_arr, 'backgroundColor': '#2ECC71'}
                    ]
                }
            }
        }

# --- Inherited Models remains the same as your previous correct version ---
class AccountMove(models.Model):
    _inherit = 'account.move'
    payment_lead_time = fields.Integer(compute='_compute_payment_lead_time', string='Lead Time (Days)', store=True)
    overdue_days = fields.Integer(compute='_compute_overdue_days', string='Overdue Days')

    @api.depends('invoice_date', 'invoice_date_due')
    def _compute_payment_lead_time(self):
        for move in self:
            if move.invoice_date and move.invoice_date_due:
                move.payment_lead_time = (move.invoice_date_due - move.invoice_date).days
            else:
                move.payment_lead_time = 0

    def _compute_overdue_days(self):
        today = fields.Date.context_today(self)
        for move in self:
            if move.state == 'posted' and move.payment_state in ('not_paid', 'partial') and move.invoice_date_due and move.invoice_date_due < today:
                move.overdue_days = (today - move.invoice_date_due).days
            else:
                move.overdue_days = 0

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    purchase_price_unit = fields.Float(related='purchase_line_id.price_unit', string='PO Price', readonly=True)
    price_variance = fields.Float(compute='_compute_variances', string='Price Variance', store=True)
    qty_variance = fields.Float(compute='_compute_variances', string='Qty Variance', store=True)

    @api.depends('price_unit', 'purchase_price_unit', 'quantity', 'purchase_line_id.product_qty')
    def _compute_variances(self):
        for line in self:
            if line.purchase_line_id and line.move_id.move_type == 'in_invoice':
                line.price_variance = line.price_unit - line.purchase_price_unit
                line.qty_variance = line.quantity - line.purchase_line_id.product_qty
            else:
                line.price_variance = 0.0
                line.qty_variance = 0.0