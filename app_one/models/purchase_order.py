from odoo import models, fields, api
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError

class PurchaseOrderExtension(models.Model):
    _inherit = 'purchase.order'

    price_variance = fields.Float(string="Price Variance", compute="_compute_price_variance", store=True)
    po_lead_time = fields.Float(string='PO Lead Time (Days)',compute="_compute_po_lead_time",store=True)
    is_emergency = fields.Boolean(string="Is Emergency", compute="_compute_is_emergency", store=True)
    # ///////////////////////////////////////////////////////////////////////////

    # compute variance
    @api.depends('order_line.price_unit', 'requisition_id')
    def _compute_price_variance(self):
        for rec in self:
            total_saving = 0.0
            count = 0
            if rec.requisition_id:
                for line in rec.order_line:

                    blanket_line = rec.requisition_id.line_ids.filtered(lambda l: l.product_id == line.product_id)

                    if blanket_line and blanket_line[0].price_unit > 0:
                        blanket_price = blanket_line[0].price_unit
                        market_price = line.price_unit


                        if market_price > 0:
                            line_saving = ((market_price - blanket_price) / market_price)
                            total_saving += line_saving
                            count += 1

                rec.price_variance = (total_saving / count ) if count > 0 else 0.0
            else:
                rec.price_variance = 0.0
    # ///////////////////////////////////////////////////////////////////////////
    # compute emergency
    @api.depends('date_approve', 'date_planned')
    def _compute_is_emergency(self):
        for rec in self:
            if rec.date_approve and rec.date_planned:

                diff = (rec.date_planned.date() - rec.date_approve.date()).days
                rec.is_emergency = diff < 2
            else:
                rec.is_emergency = False

    # ///////////////////////////////////////////////////////////////////////////

    # Lead time (performance of employees)
    @api.depends('state', 'date_approve', 'create_date')
    def _compute_po_lead_time(self):
        for rec in self:
            if rec.state in ['purchase', 'done'] and rec.date_approve and rec.create_date:
                # حساب الفرق بين تاريخ الاعتماد وتاريخ الإنشاء
                diff = rec.date_approve - rec.create_date

                rec.po_lead_time = diff.total_seconds() / 86400.0
            else:
                rec.po_lead_time = 0.0

 # ///////////////////////////////////////////////////////////////////////////

class PurchaseDashboard(models.Model):
    _name = 'wb.po.dashboard'
    _description = 'Purchase Dashboard'

    # /////////////////////////////////////////////////////////////////////////////
    # Vendor Concentration Risk
    @api.model
    def _get_vendor_concentration_data(self, domain):

        v_group = self.env['purchase.order'].read_group(
            domain,
            ['partner_id', 'amount_total:sum'],
            ['partner_id'],
            orderby='amount_total desc'
        )

        labels = []
        values = []
        other_amount = 0.0

        for i, v in enumerate(v_group):
            if v.get('partner_id'):
                if i < 5:
                    labels.append(v['partner_id'][1])
                    values.append(v['amount_total'])
                else:
                    other_amount += v['amount_total']

        if other_amount > 0:
            labels.append('other vendors')
            values.append(round(other_amount, 2))

        total_spend = sum(values)
        max_risk = (max(values) / total_spend * 100) if total_spend > 0 else 0

        return {'labels': labels, 'values': values,'max_risk': round(max_risk, 1)}


    # /////////////////////////////////////////////////////////////////////////////
    # Lead time (performance of employees)
    @api.model
    def _get_employee_performance(self, domain):
        e_group = self.env['purchase.order'].read_group(
            domain,
            ['user_id', 'po_lead_time:avg'],
            ['user_id']
        )
        names = []
        delays = []
        sorted_group = sorted(e_group, key=lambda x: x.get('po_lead_time') or 0, reverse=True)[:5]

        for e in sorted_group:
            if e.get('user_id'):
                names.append(e['user_id'][1])
                delays.append(round(e.get('po_lead_time') or 0, 2))
        return {'names': names, 'delays': delays}
    # ///////////////////////////////////////////////////////////
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

        res = self.env['purchase.order'].read_group(base_domain, ['price_variance:avg','po_lead_time:avg'], [])
        data = res[0] if res else {}
        # total_orders = self.env['purchase.order'].search_count(base_domain)
        vendor_risk = self._get_vendor_concentration_data(base_domain)
        delay_stats = self._get_delay_analysis(base_domain)
        employee_perf = self._get_employee_performance(base_domain)

        return {
            'stats': {
                'avg_savings': round(data.get('price_variance', 0) * 100, 2),
                'avg_lead_time': round(data.get('po_lead_time', 0.0), 2),
                'emergency_count': self.env['purchase.order'].search_count(base_domain + [('is_emergency', '=', True)]),
                # 'total_orders': total_orders,
                'total_delay_days': round(delay_stats['avg_total_delay'], 2),
                'max_risk': vendor_risk['max_risk'],
            },
            'late_vendor_names': delay_stats['late_names'],
            'late_vendor_values': delay_stats['late_values'],
            'employee_names': employee_perf['names'],
            'employee_delays': employee_perf['delays'],
            'vendor_spending_labels': vendor_risk['labels'],
            'vendor_spending_values': vendor_risk['values'],
        }

      # vendor delay in delivery (performance of vendors)
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




