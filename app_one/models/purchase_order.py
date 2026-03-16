from odoo import models, fields, api
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError

# 1. إضافة الحقول للموديل الأصلي للمشتريات
class PurchaseOrderExtension(models.Model):
    _inherit = 'purchase.order'

    price_variance = fields.Float(string="Price Variance", compute="_compute_custom_stats", store=True)
    touches_count = fields.Integer(string="Touches Count", default=0)
    is_emergency = fields.Boolean(string="Is Emergency", compute="_compute_is_emergency", store=True)

    @api.depends('order_line.price_unit')
    def _compute_custom_stats(self):
        for rec in self:

            rec.price_variance = 0.0

    @api.depends('date_approve', 'date_planned')
    def _compute_is_emergency(self):
        for rec in self:
            if rec.date_approve and rec.date_planned:
                # حساب الفرق بالأيام
                diff = (rec.date_planned.date() - rec.date_approve.date()).days
                rec.is_emergency = diff < 2
            else:
                rec.is_emergency = False
class PurchaseDashboard(models.Model):
    _name = 'wb.po.dashboard'
    _description = 'Purchase Dashboard'

    @api.model
    def get_purchase_stats(self, start_date=None, end_date=None, **kwargs):
        if isinstance(start_date, str) and start_date:
            StartDate = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            StartDate = datetime.now() - timedelta(days=7)

        if isinstance(end_date, str) and end_date:
            EndDate = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        else:
            EndDate = datetime.now()

        today = date.today()
        if StartDate.date() > today or EndDate.date() > today:
            raise UserError("Not Valid Date: You should enter a date less than or equal to today.")

        base_domain = [
            ('date_order', '>=', StartDate),
            ('date_order', '<=', EndDate),
            ('state', 'in', ['purchase', 'done'])
        ]

        res = self.env['purchase.order'].read_group(base_domain, ['price_variance:avg', 'touches_count:sum'], [])
        data = res[0] if res else {}
        total_orders = self.env['purchase.order'].search_count(base_domain)

        delay_stats = self._get_delay_analysis(base_domain)
        vendor_perf = self._get_vendor_performance(base_domain)

        return {
            'stats': {
                # نرسل أرقاماً فقط لكي يقبل الـ XML الحساب عليها
                'avg_savings': round(data.get('price_variance', 0) * 100, 2),
                'stability_rate': round((data.get('touches_count', 0) / (total_orders or 1)), 2),
                'emergency_count': self.env['purchase.order'].search_count(base_domain + [('is_emergency', '=', True)]),
                'total_orders': total_orders,
                'total_delay_days': round(delay_stats['avg_total_delay'], 2),
            },
            'late_vendor_names': delay_stats['late_names'],
            'late_vendor_values': delay_stats['late_values'],
            'vendor_labels': vendor_perf['labels'],
            'chart_vendor_data': vendor_perf['values'],
        }

    @api.model
    def _get_delay_analysis(self, domain):
        orders = self.env['purchase.order'].search(domain)
        total_delay = 0
        vendor_delays = {}
        for order in orders:
            if order.date_planned and order.effective_date:
                delay = max(0, (order.effective_date.date() - order.date_planned.date()).days)
                total_delay += delay
                v_name = order.partner_id.name or "Unknown"
                if v_name not in vendor_delays: vendor_delays[v_name] = []
                vendor_delays[v_name].append(delay)

        late_results = [{'name': n, 'delay': sum(d) / len(d)} for n, d in vendor_delays.items() if sum(d) / len(d) > 0]
        top_5 = sorted(late_results, key=lambda x: x['delay'], reverse=True)[:5]

        return {
            'avg_total_delay': total_delay / len(orders) if orders else 0,
            'late_names': [x['name'] for x in top_5],
            'late_values': [round(x['delay'], 1) for x in top_5]
        }

    @api.model
    def _get_vendor_performance(self, domain):
        v_group = self.env['purchase.order'].read_group(domain, ['partner_id', 'price_variance:avg'], ['partner_id'])
        labels = [v['partner_id'][1] for v in v_group if v.get('partner_id')]
        values = [round(v.get('price_variance', 0) * 100, 2) for v in v_group]
        return {'labels': labels, 'values': values}