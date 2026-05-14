from odoo import models, fields, api
from odoo.osv import expression
from datetime import datetime, timedelta, date
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class CashFlowDashboard(models.Model):
    _name = 'wb.cashflow.dashboard'
    _description = 'Cash Flow KPI Dashboard'

    # Security Whitelists for account.payment
    ALLOWED_FIELDS = {
        'name', 'state', 'payment_type', 'partner_type', 'date',
        'amount', 'partner_id', 'journal_id', 'company_id', 'currency_id'
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
        # Fetch Bank and Cash journals
        journals = self.env['account.journal'].search_read([('type', 'in', ['bank', 'cash'])], ['id', 'name'])
        companies = self.env['res.company'].search_read([], ['id', 'name'])

        # Get Whitelisted Fields for Custom Filters & Grouping
        fields_data = self.env['account.payment'].fields_get(list(self.ALLOWED_FIELDS))
        model_fields = []
        for fname, fdata in fields_data.items():
            if fdata.get('searchable') or fdata.get('store'):
                model_fields.append({
                    'name': fname, 'string': fdata.get('string'),
                    'type': fdata.get('type'), 'selection': fdata.get('selection', [])
                })
        model_fields = sorted(model_fields, key=lambda x: x['string'])

        return {
            'journals': journals,
            'companies': companies,
            'model_fields': model_fields
        }

    @api.model
    def get_cashflow_dashboard_data(self, **kwargs):
        period = kwargs.get('period', 30)
        date_from = kwargs.get('date_from', False)
        date_to = kwargs.get('date_to', False)
        journal_id = kwargs.get('journal_id', 'all')
        payment_type = kwargs.get('payment_type', 'all')
        partner_type = kwargs.get('partner_type', 'all')

        search_query = kwargs.get('search_query', '')
        active_filters = kwargs.get('active_filters', {})
        custom_domain_list = kwargs.get('custom_domain', [])
        group_by_list = kwargs.get('group_by_list', [])

        # Time Logic
        if date_from and date_to:
            current_date_start = datetime.strptime(date_from, '%Y-%m-%d').date()
            current_date_end = datetime.strptime(date_to, '%Y-%m-%d').date()
            if current_date_start > current_date_end:
                current_date_start, current_date_end = current_date_end, current_date_start
        else:
            period = int(period) if period and int(period) > 0 else 30
            current_date_end = date.today()
            current_date_start = current_date_end - timedelta(days=period)

        # Base domain targets posted payments
        time_domain = [
            ('state', '=', 'posted'),
            ('date', '>=', current_date_start),
            ('date', '<=', current_date_end)
        ]

        and_tuples = []

        # Standard Filters
        if journal_id and journal_id != 'all': and_tuples.append(('journal_id', '=', int(journal_id)))
        if payment_type and payment_type != 'all': and_tuples.append(('payment_type', '=', payment_type))
        if partner_type and partner_type != 'all': and_tuples.append(('partner_type', '=', partner_type))

        # Active UI Filters
        if active_filters.get('internal_transfers'):
            and_tuples.append(('is_internal_transfer', '=', True))
        else:
            and_tuples.append(('is_internal_transfer', '=', False))

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
        if and_tuples: final_domain_list.append(and_tuples)

        # Search Query
        if search_query:
            search_domain = ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]
            final_domain_list.append(search_domain)

        nav_domain = expression.AND(final_domain_list)
        payments = self.env['account.payment'].search(nav_domain)

        # KPIs
        total_cash_in = sum(p.amount for p in payments if p.payment_type == 'inbound')
        total_cash_out = sum(p.amount for p in payments if p.payment_type == 'outbound')
        net_cash_flow = total_cash_in - total_cash_out

        total_transactions = len(payments)
        avg_transaction_value = (total_cash_in + total_cash_out) / total_transactions if total_transactions > 0 else 0

        # --- NEW ANALYTICS: Three Pillars (CFO, CFI, CFF) ---
        cfo, cfi, cff = 0, 0, 0
        for p in payments:
            impact = p.amount if p.payment_type == 'inbound' else -p.amount
            if p.partner_type in ['customer', 'supplier']:
                cfo += impact
            elif p.is_internal_transfer:
                cfi += impact
            else:
                cff += impact

        # --- NEW ANALYTICS: Ratios ---
        net_income_move = self.env['account.move.line'].read_group(
            [('date', '>=', current_date_start), ('date', '<=', current_date_end),
             ('account_id.internal_group', 'in', ['income', 'expense']), ('move_id.state', '=', 'posted')],
            ['balance'], []
        )
        net_income = -(net_income_move[0]['balance'] or 0)
        quality_of_income = (cfo / net_income) if net_income != 0 else 0

        liabilities = self.env['account.move.line'].read_group(
            [('account_id.internal_group', '=', 'liability'), ('move_id.state', '=', 'posted')],
            ['balance'], []
        )
        total_liabilities = abs(liabilities[0]['balance'] or 1)
        coverage_ratio = cfo / total_liabilities

        # Chart Data
        daily_in, daily_out = {}, {}
        journal_balances = {}
        top_inbound_partners = {}
        top_outbound_partners = {}

        for p in payments:
            day_key = p.date.strftime('%Y-%m-%d') if p.date else 'Unknown'
            j_name = p.journal_id.name or 'Unknown Journal'
            partner_name = p.partner_id.name or 'No Partner / Internal'

            if p.payment_type == 'inbound':
                daily_in[day_key] = daily_in.get(day_key, 0) + p.amount
                journal_balances[j_name] = journal_balances.get(j_name, 0) + p.amount
                top_inbound_partners[partner_name] = top_inbound_partners.get(partner_name, 0) + p.amount
            elif p.payment_type == 'outbound':
                daily_out[day_key] = daily_out.get(day_key, 0) + p.amount
                journal_balances[j_name] = journal_balances.get(j_name, 0) - p.amount
                top_outbound_partners[partner_name] = top_outbound_partners.get(partner_name, 0) + p.amount

        # Trend Compilation
        all_dates = sorted(list(set(list(daily_in.keys()) + list(daily_out.keys()))))
        trend_in = [daily_in.get(d, 0) for d in all_dates]
        trend_out = [daily_out.get(d, 0) for d in all_dates]
        trend_net = [daily_in.get(d, 0) - daily_out.get(d, 0) for d in all_dates]

        # Sorting Partners
        sorted_inbound = sorted(top_inbound_partners.items(), key=lambda x: x[1], reverse=True)[:5]
        sorted_outbound = sorted(top_outbound_partners.items(), key=lambda x: x[1], reverse=True)[:5]

        # Dynamic Group By Logic
        dynamic_chart_labels, dynamic_chart_data = [], []
        if group_by_list:
            dynamic_chart_dict = {}
            for p in payments:
                label_parts = [str(self._get_field_display_value(p, gb)) for gb in group_by_list if
                               gb in self.ALLOWED_FIELDS]
                if label_parts:
                    label = " / ".join(label_parts)
                    # For dynamic, we aggregate net impact
                    impact = p.amount if p.payment_type == 'inbound' else -p.amount
                    dynamic_chart_dict[label] = dynamic_chart_dict.get(label, 0) + impact

            # Sort by absolute impact size
            sorted_dynamic = sorted(dynamic_chart_dict.items(), key=lambda x: abs(x[1]), reverse=True)
            dynamic_chart_labels = [i[0] for i in sorted_dynamic]
            dynamic_chart_data = [round(i[1], 2) for i in sorted_dynamic]

        return {
            'total_cash_in': round(total_cash_in, 2),
            'total_cash_out': round(total_cash_out, 2),
            'net_cash_flow': round(net_cash_flow, 2),
            'total_transactions': total_transactions,
            'avg_transaction_value': round(avg_transaction_value, 2),

            'cfo': round(cfo, 2),
            'cfi': round(cfi, 2),
            'cff': round(cff, 2),
            'quality_of_income': round(quality_of_income, 2),
            'coverage_ratio': round(coverage_ratio, 2),

            'trend_labels': all_dates,
            'trend_in': trend_in,
            'trend_out': trend_out,
            'trend_net': trend_net,

            'journal_labels': list(journal_balances.keys()),
            'journal_data': [round(v, 2) for v in journal_balances.values()],

            'inbound_partner_labels': [i[0] for i in sorted_inbound],
            'inbound_partner_data': [round(i[1], 2) for i in sorted_inbound],

            'outbound_partner_labels': [i[0] for i in sorted_outbound],
            'outbound_partner_data': [round(i[1], 2) for i in sorted_outbound],

            'dynamic_chart_labels': dynamic_chart_labels,
            'dynamic_chart_data': dynamic_chart_data,

            'nav_domain': self._serialize_domain(nav_domain),
        }

    @api.model
    def export_custom_pivot_excel(self, **kwargs):
        if not xlsxwriter: return {'error': 'xlsxwriter library is not installed.'}

        # Similar domain extraction as get_dashboard_data
        domain = [('state', '=', 'posted'), ('is_internal_transfer', '=', False)]
        # apply kwargs filters to domain here (simplified for export)
        if kwargs.get('journal_id') and kwargs.get('journal_id') != 'all': domain.append(('journal_id', '=', int(kwargs.get('journal_id'))))

        payments = self.env['account.payment'].search(domain)
        export_group = kwargs.get('export_group', 'journal_id')

        pivot_data = {}
        for p in payments:
            key = 'Unknown'
            if export_group == 'journal_id':
                key = p.journal_id.name or 'Unknown Journal'
            elif export_group == 'partner_id':
                key = p.partner_id.name or 'Unknown Partner'
            elif export_group == 'date:month':
                key = p.date.strftime('%B %Y') if p.date else 'Unknown'

            if key not in pivot_data:
                pivot_data[key] = {'cash_in': 0, 'cash_out': 0, 'net': 0, 'count': 0, 'lines': []}

            if p.payment_type == 'inbound':
                pivot_data[key]['cash_in'] += p.amount
                pivot_data[key]['net'] += p.amount
            else:
                pivot_data[key]['cash_out'] += p.amount
                pivot_data[key]['net'] -= p.amount

            pivot_data[key]['count'] += 1

            if kwargs.get('detailed_excel'):
                pivot_data[key]['lines'].append({
                    'name': p.name, 'type': 'Inbound' if p.payment_type == 'inbound' else 'Outbound',
                    'amount': p.amount, 'date': str(p.date)
                })

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Cash Flow Pivot')
        if kwargs.get('detailed_excel'): sheet.outline_settings(symbols_below=False)

        header_format = workbook.add_format({'bold': True, 'bg_color': '#1e293b', 'font_color': 'white', 'border': 1})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        text_format = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f8fafc'})
        detail_text = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})

        headers = [export_group.capitalize().replace('_id', ''), 'Cash In', 'Cash Out', 'Net Flow', 'Transactions']
        for col_num, header in enumerate(headers):
            sheet.write(0, col_num, header, header_format)
            sheet.set_column(col_num, col_num, 30 if col_num == 0 else 18)

        row = 1
        for k, data in sorted(pivot_data.items(), key=lambda x: x[1]['net'], reverse=True):
            sheet.write(row, 0, str(k), text_format)
            sheet.write(row, 1, data['cash_in'], money_format)
            sheet.write(row, 2, data['cash_out'], money_format)
            sheet.write(row, 3, data['net'], money_format)
            sheet.write(row, 4, data['count'])

            if kwargs.get('detailed_excel') and 'lines' in data:
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0, f"   ↳ {line['name']} ({line['date']})", detail_text)
                    sheet.write(row, 1, line['amount'] if line['type'] == 'Inbound' else 0, money_format)
                    sheet.write(row, 2, line['amount'] if line['type'] == 'Outbound' else 0, money_format)
                    sheet.write(row, 3, line['amount'] if line['type'] == 'Inbound' else -line['amount'], money_format)
                    sheet.write(row, 4, 1)
                    sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                    row += 1
            else:
                row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'CashFlow_Export_{fields.Date.today()}.xlsx', 'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id