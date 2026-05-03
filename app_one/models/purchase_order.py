from itertools import count

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
        top_5_values = values[:5]
        max_risk = (max(top_5_values) / total_spend * 100) if total_spend > 0 else 0

        return {'labels': labels, 'values': values,'max_risk': round(max_risk, 1)}

    # //////////////////////////////////////////////////////////////////////////////////
    # Automation rate
    @api.model
    def get_po_automation_rate(self, domain):
        all_po = self.env['purchase.order'].search(domain)
        len_po = len(all_po)
        if len_po == 0:
            return 0
        auto_po = all_po.filtered(lambda po: po.group_id)
        automation_rate = (len(auto_po) / len_po) * 100
        return round(automation_rate, 2)

    # //////////////////////////////////////////////////////////////////////////////////
    # state of orders
    @api.model
    def _get_vendor_order_status(self, domain):
        groups = self.env['purchase.order'].read_group(
            domain,
            ['partner_id' , 'state'],
            ['partner_id' , 'state'],
            lazy = False
        )
        vendor_totals = {}
        for g in groups:
            if g.get('partner_id'):
                v_name = g['partner_id'][1]
                vendor_totals[v_name] = vendor_totals.get(v_name, 0) + g['__count']

        # 2. فرز الموردين تنازلياً حسب العدد واختيار أول 5 فقط
        sorted_vendors = sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)
        top_5_vendors = [v[0] for v in sorted_vendors[:5]]

        states = ['draft', 'sent', 'purchase', 'done', 'cancel']
        data = {state: [] for state in states}
        for vendor in top_5_vendors:
            for state in states:
                count = sum([g['__count'] for g in groups if g.get('partner_id') and g['partner_id'][1] == vendor and g['state'] == state])
                data[state].append(count)
        return {'vendors': top_5_vendors, 'data': data}

    # /////////////////////////////////////////////////////////////////////////////////////
    @api.model
    def get_purchase_stats(self, start_date=None, end_date=None, **kwargs):
        period = kwargs.get('period', '30')
        if period and str(period) != '0':
            EndDate = datetime.now()
            StartDate = EndDate - timedelta(days=int(period))
        else:
            StartDate = datetime.strptime(kwargs.get('start_date'), '%Y-%m-%d') if kwargs.get(
                'start_date') else datetime.now() - timedelta(days=30)
            EndDate = datetime.strptime(kwargs.get('end_date'), '%Y-%m-%d').replace(hour=23, minute=59,
                                                                                    second=59) if kwargs.get(
                'end_date') else datetime.now()
        start_date_val, end_date_val = StartDate.date(), EndDate.date()
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

        # (Dropdowns)
        if kwargs.get('vendor_id') and kwargs.get('vendor_id') != 'all':
            base_domain.append(('partner_id', '=', int(kwargs.get('vendor_id'))))

        if kwargs.get('category_id') and kwargs.get('category_id') != 'all':
            # تصفية الـ PO التي تحتوي على منتجات من هذه الفئة
            base_domain.append(('order_line.product_id.categ_id', '=', int(kwargs.get('category_id'))))

        # (Switches)
        active_filters = kwargs.get('active_filters', {})

        if active_filters.get('state_posted'):
            base_domain.append(('invoice_status', '=', 'invoiced'))

        if active_filters.get('state_draft'):
                base_domain.append(('state', '=', 'draft'))

        if active_filters.get('pay_paid'):
            # تصفية الـ PO المدفوعة بالكامل
            base_domain.append(('invoice_status', '=', 'invoiced'))


        res = self.env['purchase.order'].read_group(base_domain, ['price_variance:avg','po_lead_time:avg'], [])
        data = res[0] if res else {}

        concentration = self._get_vendor_concentration_data(base_domain)
        delay_stats = self._get_delay_analysis(base_domain)
        auto_rate = self.get_po_automation_rate(base_domain)
        order_status = self._get_vendor_order_status(base_domain)

        return {
            'stats': {
                'avg_savings': round(data.get('price_variance', 0) * 100, 2),
                'avg_lead_time': round(data.get('po_lead_time', 0.0), 2),
                'emergency_count': self.env['purchase.order'].search_count(base_domain + [('is_emergency', '=', True)]),
                'total_delay_days': round(delay_stats['avg_total_delay'], 2),
                'max_risk': concentration['max_risk'],
                'automation_rate':auto_rate,

            },
            'late_vendor_names': delay_stats['late_names'],
            'late_vendor_values': delay_stats['late_values'],
            'vendor_spending_labels': concentration['labels'],
            'vendor_spending_values': concentration['values'],
            'order_state_data':order_status['data'],
            'vendor_name':order_status['vendors'],
        }
      # ///////////////////////////////////////////////////////////////////////////////////////////

      # vendor delay in delivery (performance of vendors)
    @api.model
    def _get_delay_analysis(self, domain):
        orders = self.env['purchase.order'].search(domain)
        received_orders = orders.filtered(lambda o: o.date_planned and o.effective_date)

        if not received_orders:
            return {
                'avg_total_delay': 0.0,
                'late_names': [],
                'late_values': []
            }

        total_delay = 0
        vendor_delays = {}
        for order in received_orders:
            delay = (order.effective_date.date() - order.date_planned.date()).days
            total_delay += delay
            v_name = order.partner_id.name or "Unknown"
            if v_name not in vendor_delays:
                vendor_delays[v_name] = []
            vendor_delays[v_name].append(delay)

        avg_total = total_delay / len(received_orders)

        # حساب متوسط التأخير لكل مورد
        late_results = [{'name': n, 'delay': sum(d) / len(d)} for n, d in vendor_delays.items() if sum(d) / len(d) > 0]
        late_v = sorted(late_results, key=lambda x: x['delay'], reverse=True)
        top_5_late = late_v[:5]

        return {
            'avg_total_delay': round(avg_total, 2),
            'late_names': [x['name'] for x in top_5_late],
            'late_values': [round(x['delay'], 1) for x in top_5_late]
        }

# ////////////////////////////////////////////////////////////////////
    @api.model
    def get_filter_options(self):
       return {
        'vendors': self.env['res.partner'].search_read([('supplier_rank', '>', 0)], ['id', 'name']),
        'categories': self.env['product.category'].search_read([], ['id', 'name']),
        'journals': self.env['account.journal'].search_read([('type', '=', 'purchase')], ['id', 'name']),
        'locations': self.env['stock.location'].search_read([('usage', '=', 'internal')], ['id', 'display_name']),
    }


