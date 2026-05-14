from odoo import models, fields, api
from odoo.osv import expression
from datetime import datetime, timedelta, date
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class InvoicingDashboard(models.Model):
    _name = 'wb.invoicing.dashboard'
    _description = 'Invoicing KPI Dashboard'

    # Security Whitelists
    ALLOWED_FIELDS = {
        'name', 'state', 'payment_state', 'invoice_date', 'invoice_date_due',
        'amount_total', 'amount_residual', 'partner_id', 'invoice_user_id',
        'journal_id', 'company_id'
    }

    ALLOWED_OPERATORS = {
        '=', '!=', 'ilike', 'not ilike', '<', '>', '<=', '>=', 'in', 'not in'
    }

    def _get_field_display_value(self, record, field_name):
        field = record._fields.get(field_name)
        if not field: return 'Unknown'
        val = record[field_name]
        if not val and val != 0: return 'None'

        if field.type == 'many2one':
            return val.display_name
        elif field.type == 'selection':
            return dict(field.selection).get(val, val)
        elif field.type in ['date', 'datetime']:
            return val.strftime('%Y-%m-%d')
        else:
            return str(val)

    def _serialize_domain(self, domain):
        res = []
        for term in domain:
            if isinstance(term, (list, tuple)) and len(term) == 3:
                val = term[2]
                if isinstance(val, datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(val, date):
                    val = val.strftime('%Y-%m-%d')
                res.append([term[0], term[1], val])
            else:
                res.append(term)
        return res

    @api.model
    def get_filter_options(self):
        journals = self.env['account.journal'].search_read([('type', '=', 'sale')], ['id', 'name'])
        users = self.env['res.users'].search_read([('share', '=', False)], ['id', 'name'])
        companies = self.env['res.company'].search_read([], ['id', 'name'])

        # Get Whitelisted Fields for Custom Filters & Grouping
        fields_data = self.env['account.move'].fields_get(list(self.ALLOWED_FIELDS))
        model_fields = []
        for fname, fdata in fields_data.items():
            if fdata.get('searchable') or fdata.get('store'):
                model_fields.append({
                    'name': fname, 'string': fdata.get('string'),
                    'type': fdata.get('type'), 'selection': fdata.get('selection', [])
                })
        model_fields = sorted(model_fields, key=lambda x: x['string'])

        return {
            'journals': journals, 'users': users,
            'companies': companies, 'model_fields': model_fields
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

        # Advanced Search Args
        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])
        group_by_list = kwargs.get('group_by_list', [])

        # Time Logic
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

        time_domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', current_date_start),
            ('invoice_date', '<=', current_date_end)
        ]

        and_tuples = []

        # Standard Filters
        if journal_id and journal_id != 'all': and_tuples.append(('journal_id', '=', int(journal_id)))
        if user_id and user_id != 'all': and_tuples.append(('invoice_user_id', '=', int(user_id)))
        if company_id and company_id != 'all': and_tuples.append(('company_id', '=', int(company_id)))
        if payment_state and payment_state != 'all': and_tuples.append(('payment_state', '=', payment_state))

        # Active UI Filters
        if active_filters.get('my_invoices'): and_tuples.append(('invoice_user_id', '=', self.env.uid))

        # Custom Domain Parsing
        if custom_domain_list:
            for c_filter in custom_domain_list:
                f_name, op, val, f_type = c_filter.get('field'), c_filter.get('operator'), c_filter.get(
                    'value'), c_filter.get('type')
                if f_name not in self.ALLOWED_FIELDS or op not in self.ALLOWED_OPERATORS: continue
                if f_type in ['integer', 'float', 'monetary'] and isinstance(val, str) and val.replace('.', '',
                                                                                                       1).isdigit():
                    val = float(val)
                elif f_type == 'boolean':
                    val = True if str(val) == '1' else False
                and_tuples.append((f_name, op, val))

        final_domain_list = [time_domain]
        if and_tuples:
            final_domain_list.append(and_tuples)

        # Search Query
        if search_query:
            search_domain = ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)

        nav_domain = expression.AND(final_domain_list)
        invoices = self.env['account.move'].search(nav_domain)

        # KPIs
        total_invoiced_amount = sum(invoices.mapped('amount_total'))
        unpaid_amount = sum(invoices.mapped('amount_residual'))
        cash_collected = total_invoiced_amount - unpaid_amount

        paid_ratio = (cash_collected / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0
        unpaid_ratio = (unpaid_amount / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        today = date.today()
        overdue_invoices = invoices.filtered(
            lambda inv: inv.invoice_date_due and inv.invoice_date_due < today and inv.amount_residual > 0)
        overdue_amount = sum(overdue_invoices.mapped('amount_residual'))
        overdue_rate = (overdue_amount / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        dso = (unpaid_amount / total_invoiced_amount * delta_days) if total_invoiced_amount > 0 else 0
        written_off_amount = 0.0
        bad_debt_pct = (written_off_amount / total_invoiced_amount * 100) if total_invoiced_amount > 0 else 0

        # Chart Data
        daily_invoiced, daily_collected, customer_ar = {}, {}, {}
        for inv in invoices:
            day_key = inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else 'Unknown'
            daily_invoiced[day_key] = daily_invoiced.get(day_key, 0) + inv.amount_total
            daily_collected[day_key] = daily_collected.get(day_key, 0) + (inv.amount_total - inv.amount_residual)

            if inv.amount_residual > 0:
                c_name = inv.partner_id.name or 'Unknown'
                customer_ar[c_name] = customer_ar.get(c_name, 0) + inv.amount_residual

        sorted_dates = sorted(list(daily_invoiced.keys()))
        sorted_customers = sorted(customer_ar.items(), key=lambda x: x[1], reverse=True)[:5]

        # Dynamic Group By Logic
        dynamic_chart_labels, dynamic_chart_data = [], []
        if group_by_list:
            dynamic_chart_dict = {}
            for inv in invoices:
                label_parts = [str(self._get_field_display_value(inv, gb)) for gb in group_by_list if
                               gb in self.ALLOWED_FIELDS]
                if label_parts:
                    label = " / ".join(label_parts)
                    dynamic_chart_dict[label] = dynamic_chart_dict.get(label, 0) + inv.amount_total
            dynamic_chart_labels = list(dynamic_chart_dict.keys())
            dynamic_chart_data = [round(val, 2) for val in dynamic_chart_dict.values()]

        safe_nav_domain = self._serialize_domain(nav_domain)

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
            'trend_invoiced_data': [daily_invoiced[d] for d in sorted_dates],
            'trend_collected_data': [daily_collected[d] for d in sorted_dates],
            'customer_labels': [i[0] for i in sorted_customers],
            'customer_data': [i[1] for i in sorted_customers],

            'dynamic_chart_labels': dynamic_chart_labels,
            'dynamic_chart_data': dynamic_chart_data,

            'nav_domain': safe_nav_domain,
        }

    @api.model
    def export_custom_pivot_excel(self, **kwargs):
        if not xlsxwriter:
            return {'error': 'xlsxwriter library is not installed on the server.'}

        date_from, date_to = kwargs.get('date_from'), kwargs.get('date_to')
        journal_id, user_id = kwargs.get('journal_id'), kwargs.get('user_id')
        company_id = kwargs.get('company_id')
        payment_state = kwargs.get('payment_state', 'all')
        detailed_excel = kwargs.get('detailed_excel', False)

        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])

        and_tuples = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]

        if date_from and date_to:
            and_tuples += [('invoice_date', '>=', date_from), ('invoice_date', '<=', date_to)]

        if journal_id and journal_id != 'all': and_tuples.append(('journal_id', '=', int(journal_id)))
        if user_id and user_id != 'all': and_tuples.append(('invoice_user_id', '=', int(user_id)))
        if company_id and company_id != 'all': and_tuples.append(('company_id', '=', int(company_id)))
        if payment_state and payment_state != 'all': and_tuples.append(('payment_state', '=', payment_state))

        if active_filters.get('my_invoices'): and_tuples.append(('invoice_user_id', '=', self.env.uid))

        if custom_domain_list:
            for c_filter in custom_domain_list:
                f_name, op, val, f_type = c_filter.get('field'), c_filter.get('operator'), c_filter.get(
                    'value'), c_filter.get('type')
                if f_name not in self.ALLOWED_FIELDS or op not in self.ALLOWED_OPERATORS: continue
                if f_type in ['integer', 'float', 'monetary'] and isinstance(val, str) and val.replace('.', '',
                                                                                                       1).isdigit():
                    val = float(val)
                elif f_type == 'boolean':
                    val = True if str(val) == '1' else False
                and_tuples.append((f_name, op, val))

        final_domain_list = []
        if and_tuples:
            final_domain_list.append(and_tuples)

        if search_query:
            search_domain = ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)

        domain = expression.AND(final_domain_list) if final_domain_list else []
        invoices = self.env['account.move'].search(domain)

        export_group = kwargs.get('export_group', 'partner_id')
        export_measures = kwargs.get('export_measures', ['invoiced'])

        pivot_data = {}
        for inv in invoices:
            key = 'Unknown'
            if export_group == 'partner_id':
                key = inv.partner_id.name or 'Unknown Customer'
            elif export_group == 'user_id':
                key = inv.invoice_user_id.name or 'Unknown Salesperson'
            elif export_group == 'journal_id':
                key = inv.journal_id.name or 'Unknown Journal'

            if key not in pivot_data:
                pivot_data[key] = {'invoiced': 0, 'collected': 0, 'unpaid': 0, 'count': 0, 'lines': []}

            collected = inv.amount_total - inv.amount_residual

            pivot_data[key]['invoiced'] += inv.amount_total
            pivot_data[key]['collected'] += collected
            pivot_data[key]['unpaid'] += inv.amount_residual
            pivot_data[key]['count'] += 1

            if detailed_excel:
                pivot_data[key]['lines'].append({
                    'name': inv.name,
                    'invoiced': inv.amount_total,
                    'collected': collected,
                    'unpaid': inv.amount_residual,
                    'date': str(inv.invoice_date)
                })

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Invoicing Pivot')
        if detailed_excel: sheet.outline_settings(symbols_below=False)

        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_format = workbook.add_format({'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f8fafc'})
        detail_text_format = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})
        detail_money_format = workbook.add_format(
            {'num_format': '#,##0.00', 'border': 1, 'font_color': '#475569', 'bg_color': '#ffffff'})

        group_titles = {'journal_id': 'Sales Journal', 'user_id': 'Salesperson', 'partner_id': 'Customer'}
        headers = [group_titles.get(export_group, 'Group')]

        if 'invoiced' in export_measures: headers.append('Total Invoiced (EGP)')
        if 'collected' in export_measures: headers.append('Cash Collected (EGP)')
        if 'unpaid' in export_measures: headers.append('Unpaid Amount (EGP)')
        headers.append('Invoices Count')

        for col_num, header in enumerate(headers):
            sheet.write(0, col_num, header, header_format)
            sheet.set_column(col_num, col_num, 35 if col_num == 0 else 18)

        row = 1
        for k, data in sorted(pivot_data.items(), key=lambda x: x[1]['invoiced'], reverse=True):
            sheet.write(row, 0, str(k), text_format)
            col = 1
            if 'invoiced' in export_measures: sheet.write(row, col, data['invoiced'], money_format); col += 1
            if 'collected' in export_measures: sheet.write(row, col, data['collected'], money_format); col += 1
            if 'unpaid' in export_measures: sheet.write(row, col, data['unpaid'], money_format); col += 1
            sheet.write(row, col, data['count'], num_format)

            if detailed_excel and 'lines' in data:
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0, f"   ↳ {line['name']} ({line['date']})", detail_text_format)
                    col = 1
                    if 'invoiced' in export_measures: sheet.write(row, col, line['invoiced'],
                                                                  detail_money_format); col += 1
                    if 'collected' in export_measures: sheet.write(row, col, line['collected'],
                                                                   detail_money_format); col += 1
                    if 'unpaid' in export_measures: sheet.write(row, col, line['unpaid'], detail_money_format); col += 1
                    sheet.write(row, col, 1, detail_money_format)
                    sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                    row += 1
            else:
                row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'Invoicing_Export_{fields.Date.today()}.xlsx', 'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id