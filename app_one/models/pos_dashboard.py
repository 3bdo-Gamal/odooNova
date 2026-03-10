from odoo import models, fields, api
from datetime import datetime, timedelta
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class PosDashboard(models.Model):
    _name = 'wb.pos.dashboard'
    _description = 'POS KPI Dashboard'

    @api.model
    def get_filter_options(self):
        pos_configs = self.env['pos.config'].search_read([], ['id', 'name'])
        users = self.env['res.users'].search_read([('share', '=', False)], ['id', 'name'])
        categories = self.env['product.category'].search_read([], ['id', 'name'])
        # إضافة طرق الدفع الخاصة بنقاط البيع
        payment_methods = self.env['pos.payment.method'].search_read([], ['id', 'name'])

        return {
            'pos_configs': pos_configs, 'users': users,
            'categories': categories, 'payment_methods': payment_methods
        }

    @api.model
    def get_pos_dashboard_data(self, **kwargs):
        period = kwargs.get('period', 7)
        date_from = kwargs.get('date_from', False)
        date_to = kwargs.get('date_to', False)
        config_id = kwargs.get('config_id', 'all')
        user_id = kwargs.get('user_id', 'all')
        category_id = kwargs.get('category_id', 'all')
        company_id = kwargs.get('company_id', 'all')
        state = kwargs.get('state', 'paid')

        payment_method_id = kwargs.get('payment_method_id', 'all')
        native_domain = kwargs.get('native_domain', [])
        top_products_limit = int(kwargs.get('top_products', 5))



        # تظبيط التواريخ
        if date_from and date_to:
            current_date_start = datetime.strptime(date_from, '%Y-%m-%d')
            current_date_end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            if current_date_start > current_date_end:
                current_date_start, current_date_end = current_date_end, current_date_start
                current_date_end = current_date_end.replace(hour=23, minute=59, second=59)
        else:
            period = int(period) if period and int(period) > 0 else 7
            current_date_end = datetime.now()
            current_date_start = current_date_end - timedelta(days=period)

        time_domain = [('date_order', '>=', current_date_start), ('date_order', '<=', current_date_end)]

        # تظبيط الفلاتر الديناميكية (عشان الفلاتر تهز الداتا كلها)
        extra_domain = []
        if config_id and config_id != 'all': extra_domain.append(('session_id.config_id', '=', int(config_id)))
        if user_id and user_id != 'all': extra_domain.append(('user_id', '=', int(user_id)))
        if category_id and category_id != 'all': extra_domain.append(
            ('lines.product_id.categ_id', 'child_of', int(category_id)))
        if company_id and company_id != 'all': extra_domain.append(('company_id', '=', int(company_id)))
        if payment_method_id and payment_method_id != 'all':
            extra_domain.append(('payment_ids.payment_method_id', '=', int(payment_method_id)))

        if native_domain: extra_domain += native_domain

        nav_domain = time_domain + extra_domain
        all_period_orders = self.env['pos.order'].search(nav_domain)

        # فلترة حسب الحالة (مدفوع، مفوتر، أو الكل ما عدا الملغي)
        if state and state != 'all':
            orders = all_period_orders.filtered(lambda o: o.state == state)
        else:
            orders = all_period_orders.filtered(lambda o: o.state != 'cancel')



        # 1 & 2: POS Revenue & Orders Count
        pos_revenue = sum(orders.mapped('amount_total'))
        pos_orders_count = len(orders)

        gross_sales = 0
        refunded_amount = 0
        total_discount = 0
        hourly_sales = {str(i).zfill(2): 0 for i in range(24)}
        product_sales = {}

        for order in orders:
            # فصل المبيعات الإجمالية عن المرتجعات
            if order.amount_total < 0:
                refunded_amount += abs(order.amount_total)
            else:
                gross_sales += order.amount_total

            # 3: Revenue per Hour
            if order.date_order:
                hour = order.date_order.strftime('%H')
                hourly_sales[hour] += order.amount_total

            # حساب الخصومات من سطور الطلب
            for line in order.lines:  # في الـ POS اسمها lines مش order_line
                p_name = line.product_id.name or 'Unknown'
                product_sales[p_name] = product_sales.get(p_name, 0) + line.qty

                if line.discount > 0:
                    original_price = line.price_unit * line.qty
                    total_discount += original_price * (line.discount / 100)

        # 4 & 5: Cash & Card Ratios
        total_cash = 0
        total_card = 0
        payments = orders.mapped('payment_ids')
        for payment in payments:
            # بنشيك على نوع الجورنال المرتبط بطريقة الدفع
            if payment.payment_method_id.journal_id.type == 'cash':
                total_cash += payment.amount
            elif payment.payment_method_id.journal_id.type == 'bank':
                total_card += payment.amount

        total_payments = total_cash + total_card
        cash_ratio = (total_cash / total_payments * 100) if total_payments > 0 else 0
        card_ratio = (total_card / total_payments * 100) if total_payments > 0 else 0

        # 6: Discount %
        discount_pct = (total_discount / gross_sales * 100) if gross_sales > 0 else 0

        # 7: POS Refund Rate
        refund_rate = (refunded_amount / gross_sales * 100) if gross_sales > 0 else 0


        # تظبيط الداتا للرسومات البيانية
        sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:top_products_limit]


        return {
            'pos_revenue': round(pos_revenue, 2),
            'pos_orders_count': pos_orders_count,
            'cash_ratio': round(cash_ratio, 2),
            'card_ratio': round(card_ratio, 2),
            'discount_pct': round(discount_pct, 2),
            'refund_rate': round(refund_rate, 2),
            'hourly_labels': list(hourly_sales.keys()),
            'hourly_data': [round(val, 2) for val in hourly_sales.values()],
            'product_labels': [i[0] for i in sorted_products],
            'product_data': [i[1] for i in sorted_products],
            'nav_domain': nav_domain,
        }

    @api.model
    def export_custom_pivot_excel(self, **kwargs):
        # نفس اللوجيك بتاعك بالظبط بس متعدل يقرأ من pos.order و lines
        date_from, date_to = kwargs.get('date_from'), kwargs.get('date_to')
        config_id, user_id = kwargs.get('config_id'), kwargs.get('user_id')
        category_id, company_id = kwargs.get('category_id'), kwargs.get('company_id')
        payment_method_id = kwargs.get('payment_method_id', 'all')
        detailed_excel = kwargs.get('detailed_excel', False)
        native_domain = kwargs.get('native_domain', [])
        payment_method_id = kwargs.get('payment_method_id', 'all')

        domain = []
        if date_from and date_to:
            domain += [('date_order', '>=', f"{date_from} 00:00:00"), ('date_order', '<=', f"{date_to} 23:59:59")]
        if config_id and config_id != 'all': domain.append(('session_id.config_id', '=', int(config_id)))
        if user_id and user_id != 'all': domain.append(('user_id', '=', int(user_id)))
        if category_id and category_id != 'all': domain.append(
            ('lines.product_id.categ_id', 'child_of', int(category_id)))
        if company_id and company_id != 'all': domain.append(('company_id', '=', int(company_id)))
        if payment_method_id and payment_method_id != 'all':
            domain.append(('payment_ids.payment_method_id', '=', int(payment_method_id)))

        if native_domain: domain += native_domain


        orders = self.env['pos.order'].search(domain).filtered(lambda o: o.state != 'cancel')
        export_group = kwargs.get('export_group', 'user_id')
        export_measures = kwargs.get('export_measures', ['revenue'])

        pivot_data = {}
        for order in orders:
            key = 'Unknown'
            if export_group == 'partner_id':
                key = order.partner_id.name or 'Walk-in Customer'
            elif export_group == 'user_id':
                key = order.user_id.name or 'Unknown'
            elif export_group == 'config_id':
                key = order.session_id.config_id.name or 'Unknown'

            if export_group in ['product_id', 'categ_id']:
                for line in order.lines:
                    line_key = line.product_id.name if export_group == 'product_id' else line.product_id.categ_id.name
                    line_key = line_key or 'Unknown'
                    if line_key not in pivot_data:
                        pivot_data[line_key] = {'revenue': 0, 'qty': 0, 'discount': 0, 'orders': set(), 'lines': []}

                    pivot_data[line_key]['revenue'] += line.price_subtotal_incl
                    pivot_data[line_key]['qty'] += line.qty
                    disc = (line.price_unit * line.qty) * (line.discount / 100) if line.discount else 0
                    pivot_data[line_key]['discount'] += disc
                    pivot_data[line_key]['orders'].add(order.id)
            else:
                if key not in pivot_data:
                    pivot_data[key] = {'revenue': 0, 'qty': 0, 'discount': 0, 'orders': set(), 'lines': []}


                pivot_data[key]['revenue'] += order.amount_total
                pivot_data[key]['orders'].add(order.id)
                order_disc, order_qty = 0, 0
                for line in order.lines:
                    order_qty += line.qty
                    if line.discount > 0:
                        order_disc += (line.price_unit * line.qty) * (line.discount / 100)

                pivot_data[key]['qty'] += order_qty
                pivot_data[key]['discount'] += order_disc

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('POS Pivot Analysis')

        # ... (باقي كود تصميم الإكسيل زي ما هو بالظبط من الكود بتاعك) ...
        # اختصرتهولك هنا عشان نركز على الداتا، بس هتحط نفس تنسيقات الـ formats بتاعتك

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'POS_Export_{fields.Date.today()}.xlsx', 'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id