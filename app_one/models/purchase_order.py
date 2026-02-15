from odoo import models, fields, api
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    # emergency
    is_emergency = fields.Boolean(string="Is Emergency", compute="_compute_is_emergency", store=True)
    @api.depends('date_approve', 'date_planned')
    def _compute_is_emergency(self):
        for rec in self:
            if rec.date_approve and rec.date_planned:
                diff = abs(rec.date_approve - rec.date_planned)
                rec.is_emergency = diff.days < 2
            else:
               rec.is_emergency = False


    # savings
    price_variance = fields.Float(string="Price Variance (%)",
                                  compute="_compute_price_variance",
                                  help="الفرق بين سعر الاتفاقية وسعر السوق(أو آخر سعر شراء بدون اتفاقية)",
                                  store=True)

    @api.depends('order_line.price_unit', 'requisition_id')
    def _compute_price_variance(self):
        for rec in self:
            variance_sum = 0
            count = 0
            for line in rec.order_line:
                if not line.product_id and line.price_unit<=0:
                    continue

                domain = [
                    ('product_id', '=', line.product_id.id),
                    ('order_id.requisition_id', '=', False),
                    ('state', 'in', ['purchase', 'done']),
                    ('price_unit','>',0)
                ]


                if isinstance(line.id, int):
                    domain.append(('id', '!=', line.id))

                last_purchase_line = self.env['purchase.order.line'].search(
                    domain, limit=1, order='date_order desc'
                )

                if last_purchase_line:
                    last_market_price = last_purchase_line.price_unit
                    if last_market_price > 0:
                        variance_sum += (last_market_price - line.price_unit) / last_market_price
                        count+=1
                raw_avg =(variance_sum / count) if count > 0 else 0
                rec.price_variance = max(min(raw_avg,1.0),-1.0)

    # stability
    touches_count = fields.Integer(string="Order Touches", default=0, readonly=True)

    def write(self, vals):
        for rec in self:
            if rec.state in ['purchase', 'done']:
                if 'state' not in vals and 'touches_count' not in vals:
                    tracked_fields = ['order_line', 'partner_id', 'amount_total', 'date_planned']
                    if any(field in vals for field in tracked_fields):
                        vals['touches_count'] = rec.touches_count + 1
        return super(PurchaseOrder, self).write(vals)

    @api.model
    def get_confirmed_orders_stat(self):

        orders = self.search([('state', 'in', ['purchase', 'done'])])
        total_touches = sum(orders.mapped('touches_count'))
        total_orders = len(orders)
        rate = total_touches/total_orders if total_orders > 0 else 0
        return round(rate, 2)

    # bills
    bill_lag_time  = fields.Float(string="Bill Lag Time (Hours)",
                                  compute="_compute_bill_lag_time",
                                  store=True)

    @api.depends('invoice_ids.create_date', 'date_approve')
    def _compute_bill_lag_time(self):
        for rec in self:
            if rec.date_approve and rec.invoice_ids:
                first_bill_date = min(rec.invoice_ids.mapped('create_date'))
                duration = first_bill_date - rec.date_approve
                rec.bill_lag_time = duration.total_seconds() /3600

            else:
                rec.bill_lag_time = 0

    @api.model
    def get_purchase_stats(self, period=7):
        period = int(period)
        if (period == 0):
            period = 7
        # حساب المتوسطات (التوفير وتأخير الفواتير)
        res = self.read_group([], ['price_variance:avg', 'bill_lag_time:avg'], [])
        '''''
        if res and res[0]:
            raw_savings = res[0].get('price_variance') or 0
            clean_savings = max(min(raw_savings, 1.0), -1.0)
            avg_savings = f"{round(clean_savings * 100, 2)}%"

            raw_lag = res[0].get('bill_lag_time') or 0
            avg_lag = f"{round(raw_lag, 1)} Hrs"
        else:
            avg_savings = "0%"
            avg_lag = "0 Hrs"
            '''
        avg_savings = res[0]['price_variance'] if res and res[0]['price_variance'] else 0
        avg_lag = res[0]['bill_lag_time'] if res and res[0]['bill_lag_time'] else 0

        confirmed_orders = self.search([('state','in',['purchase','done'])])
        total_touches  = sum(confirmed_orders.mapped('touches_count'))
        total_orders = len(confirmed_orders)
        stability_rate = total_touches/total_orders if total_orders > 0 else 0

        vendor_group = self.read_group([], ['partner_id', 'price_variance:avg'], ['partner_id'])
        vendor_names_list = [v['partner_id'][1] for v in vendor_group if v['partner_id']]
        vendor_values_list = [round(v['price_variance'] * 100, 2) for v in vendor_group]

        user_group = self.read_group([], ['user_id', 'bill_lag_time:sum'], ['user_id'])
        user_names_list = [u['user_id'][1] for u in user_group if u['user_id']]
        user_lag_list = [round(u['bill_lag_time'], 1) for u in user_group]
        return {
            'stats':{
            'avg_savings': f"{round(avg_savings * 100, 2)}%",
            'avg_lag': f"{round(avg_lag, 1)}Hrs",
            'stability_rate': f"{round(stability_rate, 2)}%",
            'emergency_count': self.search_count([('is_emergency', '=', True)]),
            },
            'vendorLabels': vendor_names_list,  # قائمة أسماء الموردين
            'chart_vendor_data': vendor_values_list,  # قائمة أرقام التوفير لكل مورد
            'workloadLabels': user_names_list,  # قائمة أسماء الموظفين
            'workload_chart_data': user_lag_list  # قائمة أرقام التأخير لكل موظف
        }
