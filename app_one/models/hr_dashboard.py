from odoo import models, fields, api
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError
import io
import base64
from dateutil.relativedelta import relativedelta
import calendar

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
try:
    import pandas as pa
except ImportError:
    pa = None


class HR_Dashboard(models.Model):
    _name = 'wb.hr.dashboard'
    _description = 'HR KPI Dashboard'

    name = fields.Char(default="HR Dashboard")
    employee_count = fields.Integer(string='employee count')
    workload_hours = fields.Float(string="total workload hours")
    tasks_complete = fields.Integer(string=" tasks_complete")
    production_level_kpi = fields.Float(string="productivity")
    days = fields.Integer(string=' Attendance Days')
    total_work_days = fields.Integer(string='Total Work Days')
    attendance = fields.Float(string=' Employee Attendance ')
    emp_turnover = fields.Float(string=' Employee TurnOver ')
    sales_per_emp = fields.Integer(string=" Sales of Employees")
    average_leaves = fields.Float(string=" Average Leaves")
    datajson = fields.Text()

    @api.model
    def dataframe(self, start_date, end_date, department_id=None):
        emp_domain = [('active', 'in', [True, False])]
        if department_id:
            emp_domain.append(('department_id', '=', int(department_id)))
            # استخدت يوزر اي دي واي دي لاني بتعامل مع موديولز مختلفه من الhr فكل موديول ال اي دي متسمي باسم مختلف
        emp_fields = ['id', 'name', 'department_id', 'job_id', 'user_id', 'create_date', 'departure_date', 'active']
        employees = self.env['hr.employee'].with_context(active_test=False).search_read(emp_domain, emp_fields)
        if not employees:
            return pa.DataFrame() if pa else []
        user_to_emp = {e['user_id'][0]: e['id'] for e in employees if e['user_id']}
        emp_ids = [e['id'] for e in employees]
        user_ids = list(user_to_emp.keys())
        att_data = self.env['hr.attendance'].read_group([('check_in', '>=', start_date), ('check_in', '<=', end_date), ('employee_id', 'in', emp_ids)],['employee_id', 'worked_hours:sum'], ['employee_id'])
        att_map = {a['employee_id'][0]: (a.get('worked_hours', 0), a.get('__count', 0)) for a in att_data}
        leave_data = self.env['hr.leave'].read_group([('state', '=', 'validate'), ('request_date_from', '>=', start_date), ('request_date_to', '<=', end_date),('employee_id', 'in', emp_ids)], ['employee_id', 'number_of_days:sum'], ['employee_id'])
        leave_map = {l['employee_id'][0]: l.get('number_of_days', 0) for l in leave_data}
        task_data = self.env['project.task'].search_read([('create_date', '>=', start_date), ('create_date', '<=', end_date), ('user_ids', 'in', user_ids)],['user_ids', 'allocated_hours', 'state'])
        sales_data = self.env['sale.order'].read_group( [('state', 'in', ['sale', 'done']), ('date_order', '>=', start_date), ('date_order', '<=', end_date),('user_id', 'in', user_ids)],['user_id', 'amount_total:sum'], ['user_id'])
        sales_map = {s['user_id'][0]: (s.get('amount_total', 0), s.get('__count', 0)) for s in sales_data}
        user_task_stats = {}
        for t in task_data:
            u_ids = t['user_ids']
            share = (t['allocated_hours'] or 0) / len(u_ids) if u_ids else 0
            is_done = 1 if t['state'] == '1_done' else 0
            for uid in u_ids:
                stats = user_task_stats.get(uid, {'hrs': 0, 'done': 0, 'total': 0})
                stats['hrs'] += share
                stats['done'] += is_done
                stats['total'] += 1
                user_task_stats[uid] = stats

        l = []
        for e in employees:
            uid = e['user_id'][0] if e['user_id'] else None
            eid = e['id']
            t_stats = user_task_stats.get(uid, {'hrs': 0, 'done': 0, 'total': 0})
            s_stats = sales_map.get(uid, (0, 0))
            a_stats = att_map.get(eid, (0, 0))

            row = {
                'id': eid,
                'name': e['name'],
                'dept_name': e['department_id'][1].split('/')[-1].strip() if e['department_id'] else 'Unknown',
                'user_id': uid,
                'attendance_days': a_stats[1],
                'actual_worked_hours': a_stats[0],
                'total_leave_days': leave_map.get(eid, 0),
                'total_allocated_hours': t_stats['hrs'],
                'tasks_completed': t_stats['done'],
                'total_tasks': t_stats['total'],
                'sales_amount': s_stats[0],
                'sales_orders_count': s_stats[1],
                'productivity_pct': (t_stats['done'] / t_stats['total'] * 100) if t_stats['total'] > 0 else 0
            }
            l.append(row)
            # بحط الليست هنا في داتا فريم علشان تبقي التحليلات الاحصائيه بسرعه
        if pa:
            return pa.DataFrame(l)
        # لو مشتغلتش مكتبه بنداس بيرجعهم ليست علشان ميحصلش ايرور
        return l

    @api.model
    def turnover_trend(self, end_date_val, department_id, search_query):
        trend_labels = []
        trend_data = []
        for i in range(11, -1, -1):
            target_month = end_date_val - relativedelta(months=i)
            first_day = target_month.replace(day=1)
            last_day = target_month.replace(day=calendar.monthrange(target_month.year, target_month.month)[1])
            base_dom = []
            if department_id: base_dom.append(('department_id', '=', int(department_id)))
            if search_query: base_dom.append(('name', 'ilike', search_query))
            start_c = self.env['hr.employee'].with_context(active_test=False).search_count(base_dom + [('create_date', '<=', first_day), '|', ('active', '=', True),('departure_date', '>=', first_day)])
            end_c = self.env['hr.employee'].with_context(active_test=False).search_count(base_dom + [('create_date', '<=', last_day), '|', ('active', '=', True),('departure_date', '>', last_day)])
            left_c = self.env['hr.employee'].with_context(active_test=False).search_count(base_dom + [('active', '=', False), ('departure_date', '>=', first_day),('departure_date', '<=', last_day)])
            avg = (start_c + end_c) / 2.0
            rate = round((left_c / avg) * 100, 2) if avg > 0 else 0
            trend_labels.append(target_month.strftime('%b %Y'))
            trend_data.append(rate)
        return {'labels': trend_labels, 'data': trend_data}
    @api.model
    def productivity_trend(self, end_date_val, department_id, search_query):
        trend2_labels = []
        trend2_data = []
        emp_dom = [('active', '=', True)]
        if department_id: emp_dom.append(('department_id', '=', int(department_id)))
        if search_query: emp_dom.append(('name', 'ilike', search_query))
        employees = self.env['hr.employee'].search(emp_dom)
        u_ids = employees.mapped('user_id').ids
        for i in range(11, -1, -1):
            target_month = end_date_val - relativedelta(months=i)
            first_day = datetime.combine(target_month.replace(day=1), datetime.min.time())
            last_day = datetime.combine(target_month.replace(day=calendar.monthrange(target_month.year, target_month.month)[1]),datetime.max.time())
            done_this_month = self.env['project.task'].search_count([('user_ids', 'in', u_ids),('state', '=', '1_done'),('create_date', '>=', first_day),('create_date', '<=', last_day)])
            total_tasks = self.env['project.task'].search_count([('user_ids', 'in', u_ids),('create_date', '>=', first_day),('create_date', '<=', last_day),('state', '!=', '1_canceled')])
            if total_tasks > 0:
                productivity_rate = round((done_this_month / total_tasks * 100), 2)
            else:
                productivity_rate = 0
            trend2_labels.append(target_month.strftime('%b %Y'))
            trend2_data.append(productivity_rate)
        return {'labels2': trend2_labels, 'data2': trend2_data}

    @api.model
    def compute_kpis(self, *args, **kwargs):
        if args and isinstance(args[0], dict): kwargs.update(args[0])
        period = kwargs.get('period', '30')
        if period and str(period) != '0':
            EndDate = datetime.now()
            StartDate = EndDate - timedelta(days=int(period))
        else:
            StartDate = datetime.strptime(kwargs.get('start_date'), '%Y-%m-%d') if kwargs.get('start_date') else datetime.now() - timedelta(days=30)
            EndDate = datetime.strptime(kwargs.get('end_date'), '%Y-%m-%d').replace(hour=23, minute=59,second=59) if kwargs.get('end_date') else datetime.now()
        start_date_val, end_date_val = StartDate.date(), EndDate.date()
        filters = kwargs.get('filters', {})
        dept_id = filters.get('department_id')
        search = kwargs.get('search_query', '')
        group_by_list = kwargs.get('group_by_list', [])
        emp_dom = [('active', '=', True)]
        if dept_id: emp_dom.append(('department_id', '=', int(dept_id)))
        if search: emp_dom.append(('name', 'ilike', search))
        employees = self.env['hr.employee'].search(emp_dom)
        employee_count = len(employees)
        emp_ids = employees.ids
        u_ids = employees.mapped('user_id').ids
        user_emp_dict = {emp.user_id.id: emp for emp in employees if emp.user_id}
        tasks_done_count = self.env['project.task'].search_count([('create_date', '>=', StartDate), ('create_date', '<=', EndDate),('state', '=', '1_done'),('user_ids', 'in', u_ids)])
        tasks_todo = self.env['project.task'].search([('state', 'not in', ['1_done', '1_canceled']), ('create_date', '<=', EndDate), ('user_ids', 'in', u_ids)])
        total_tasks_for_kpi = self.env['project.task'].search_count([('create_date', '>=', StartDate), ('create_date', '<=', EndDate), ('user_ids', 'in', u_ids), ('state', '!=', '1_canceled')])
        workload_hours = 0
        chart_dict = {}
        chart_details = {}
        for t in tasks_todo:
            hours = t.allocated_hours or 0.0
            users = t.user_ids
            t_share = hours / len(users) if users else hours
            for u in users:
                if u.id not in u_ids: continue
                workload_hours += t_share
                lbl = u.name
                if group_by_list:
                    e = user_emp_dict.get(u.id)
                    parts = []
                    if e:
                        for gb in group_by_list:
                            if gb == 'department':
                                parts.append(e.department_id.name or "No Dept")
                            elif gb == 'manager':
                                parts.append(e.parent_id.name or "No Mgr")
                            elif gb == 'job_position':
                                parts.append(e.job_id.name or "No Pos")
                    lbl = " / ".join(parts) if parts else u.name
                chart_dict[lbl] = chart_dict.get(lbl, 0) + t_share
                chart_details.setdefault(lbl, []).append({'name': t.name or 'Task', 'hours': round(t_share, 2)})
        att_agg = self.env['hr.attendance'].read_group([('check_in', '>=', StartDate), ('check_in', '<=', EndDate), ('employee_id', 'in', emp_ids)],['employee_id'], ['employee_id', 'check_in:day'], lazy=False)
        actual_att_days = len(att_agg)
        leaves_agg = self.env['hr.leave'].read_group([('state', '=', 'validate'), ('request_date_to', '>=', start_date_val),('request_date_from', '<=', end_date_val), ('employee_id', 'in', emp_ids)], ['number_of_days:sum'], [])
        total_leaves = leaves_agg[0]['number_of_days'] if leaves_agg and leaves_agg[0]['number_of_days'] else 0
        expected_days = 0
        for e in employees:
            cal = e.resource_calendar_id or self.env.company.resource_calendar_id
            expected_days += (cal.get_work_hours_count(StartDate, EndDate) / (cal.hours_per_day or 8))
        net_days = max(0, expected_days - total_leaves)
        attendance_rate = min((actual_att_days / net_days * 100), 100) if net_days > 0 else 0
        df = self.dataframe(start_date_val, end_date_val, dept_id)
        dept_cards, scatter, workload_std, bottlenecks = [], [], 0.0, 0
        bottleneck_emp_ids = []
        labels3 = []
        means3 = []
        variances3 = []
        if pa and not df.empty:
            if len(df) > 1: workload_std = round(df['total_allocated_hours'].std(), 2)
            m_h, m_d = df['total_allocated_hours'].mean(), df['tasks_completed'].mean()
            b_df = df[(df['total_allocated_hours'] > m_h) & (df['tasks_completed'] < m_d)]
            bottlenecks = len(b_df)
            bottleneck_emp_ids = b_df['id'].tolist() if not b_df.empty else []
            for _, r in df.iterrows():
                scatter.append({'x': round(r['total_allocated_hours'], 2), 'y': int(r['tasks_completed']), 'name': r['name']})
            d_stats = df[df['dept_name'] != 'Unknown'].groupby('dept_name')[['productivity_pct', 'total_allocated_hours']].agg(['mean', 'std']).fillna(0)
            for d_n, r in d_stats.iterrows():
                prod_mean = round(r[('productivity_pct', 'mean')], 2)
                prod_std = r[('productivity_pct', 'std')]
                prod_var = round(prod_std, 2)
                work_mean = r[('total_allocated_hours', 'mean')]
                work_std_raw = r[('total_allocated_hours', 'std')]
                work_std_pct = round((work_std_raw / work_mean * 100), 2) if work_mean > 0 else 0
                labels3.append(d_n)
                means3.append(prod_mean)
                variances3.append(prod_var)
                dept_cards.append({'department': d_n,
                                   'prod_mean': prod_mean,
                                   'work_std': work_std_pct,
                                   'prod_var': prod_var})

        prod_trend_data = self.productivity_trend(end_date_val, dept_id, search)
        turnover_res = self.turnover_trend(end_date_val, dept_id, search)
        base_dom_kpi = []
        if dept_id:
            base_dom_kpi.append(('department_id', '=', int(dept_id)))
        if search:
            base_dom_kpi.append(('name', 'ilike', search))
        start_c_kpi = self.env['hr.employee'].with_context(active_test=False).search_count(base_dom_kpi + [('create_date', '<=', start_date_val), '|', ('active', '=', True),('departure_date', '>=', start_date_val)])
        end_c_kpi = self.env['hr.employee'].with_context(active_test=False).search_count(base_dom_kpi + [('create_date', '<=', end_date_val), '|', ('active', '=', True),('departure_date', '>', end_date_val)])
        left_c_kpi = self.env['hr.employee'].with_context(active_test=False).search_count(base_dom_kpi + [('active', '=', False), ('departure_date', '>=', start_date_val), ('departure_date', '<=', end_date_val)])
        avg_kpi = (start_c_kpi + end_c_kpi) / 2.0
        emp_turnover_rate = round((left_c_kpi / avg_kpi) * 100, 2) if avg_kpi > 0 else 0
        return {
            'computed_start_date': str(start_date_val),
            'computed_end_date': str(end_date_val),
            'employee_count': employee_count,
            'workload_hours': round(workload_hours, 2),
            'tasks_complete': tasks_done_count,
            'production_kpi': round((tasks_done_count / total_tasks_for_kpi * 100),2) if total_tasks_for_kpi > 0 else 0,
            'chart_labels': list(chart_dict.keys()),
            'chart_data': [round(float(v), 2) for v in chart_dict.values()],
            'chart_details': chart_details,
            'trend_labels': turnover_res['labels'],
            'trend_data': turnover_res['data'],
            'prod_trend_labels': prod_trend_data['labels2'],
            'prod_trend_data': prod_trend_data['data2'],
            'attendance': round(attendance_rate, 2),
            'emp_turnover': emp_turnover_rate,
            'sales_per_emp': len(self.env['sale.order'].read_group([('state', 'in', ['sale', 'done']), ('date_order', '>=', StartDate), ('date_order', '<=', EndDate),('user_id', 'in', u_ids)], ['user_id'], ['user_id'])),
            'absence': round(max(100.0 - attendance_rate, 0.0), 2),
            'average_leaves': round((total_leaves / expected_days * 100), 2) if expected_days > 0 else 0,
            'departments': [{'id': d.id, 'name': d.name} for d in self.env['hr.department'].search([])],
            'dept_stats_cards': dept_cards,
            'workload_std': workload_std,
            'bottleneck_emps': bottlenecks,
            'bottleneck_emp_ids': bottleneck_emp_ids,
            'scatter_data': scatter,
            'anova_labels': labels3,
            'anova_means': means3,
            'anova_variances': variances3,
        }

    @api.model
    def export_custom_pivot_excel(self, *args, **kwargs):
        if args and isinstance(args[0], dict): kwargs.update(args[0])
        export_group = kwargs.get('export_group', 'none')
        if export_group != 'none': kwargs['group_by_list'] = [export_group]
        data = self.compute_kpis(**kwargs)
        export_measures = kwargs.get('export_measures', [])
        detailed_excel = kwargs.get('detailed_excel', False)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('HR Pivot Data')
        if detailed_excel: sheet.outline_settings(symbols_below=False)
        title_format = workbook.add_format({'bold': True, 'font_size': 12})
        header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#17ac39', 'font_color': 'white', 'border': 1, 'align': 'center',
             'valign': 'vcenter', 'size': 13})
        text_format = workbook.add_format({'border': 1, 'align': 'left', 'font_size': 11})
        num_format = workbook.add_format({'border': 1, 'align': 'center', 'font_size': 11})
        detail_text = workbook.add_format(
            {'border': 1, 'indent': 1, 'font_color': '#475569', 'bg_color': '#f8fafc', 'font_size': 10})
        detail_num = workbook.add_format(
            {'border': 1, 'align': 'center', 'font_color': '#475569', 'bg_color': '#f8fafc', 'font_size': 10})
        sheet.set_column(0, 0, 35)
        sheet.set_column(1, 1, 20)
        dept_id = kwargs.get('filters', {}).get('department_id')
        dept_name = "All Departments"
        if dept_id:
            for d in data.get('departments', []):
                if d['id'] == int(dept_id):
                    dept_name = d['name']
                    break
        sheet.write(0, 0, "Department Filter", title_format)
        sheet.write(0, 1, dept_name)
        sheet.write(1, 0, "From Date", title_format)
        sheet.write(1, 1, data.get('computed_start_date', ''))
        sheet.write(2, 0, "To Date", title_format)
        sheet.write(2, 1, data.get('computed_end_date', ''))
        search_q = kwargs.get('search_query', '')
        if search_q:
            sheet.write(3, 0, "Employee Name", title_format)
            sheet.write(3, 1, search_q)
        row = 5
        sheet.write(row, 0, "Key Performance Indicator", header_format)
        sheet.write(row, 1, "Value", header_format)
        row += 1
        measures = [('emp', 'Total Employees', 'employee_count', ''),
                    ('workload', 'Total Workload', 'workload_hours', ' Hrs'),
                    ('tasks', 'Completed Tasks', 'tasks_complete', ''), ('prod', 'Productivity', 'production_kpi', '%'),
                    ('att', 'Attendance Rate', 'attendance', '%'),
                    ('turnover', 'Employee Turnover', 'emp_turnover', '%'),
                    ('sales', 'Sales Done / Emp', 'sales_per_emp', ''),
                    ('leaves', 'Vocations Rate', 'average_leaves', '%'), ('absence', 'Absence Rate', 'absence', '%')]
        for m_key, m_lbl, m_field, m_unit in measures:
            if m_key in export_measures:
                sheet.write(row, 0, m_lbl, text_format)
                val = data.get(m_field, 0)
                sheet.write(row, 1, f"{val}{m_unit}", num_format)
                row += 1
        row += 2
        if export_group != 'none':
            group_title = export_group.replace('_', ' ').title()
            sheet.write(row, 0, f"Workload Analysis Group By: {group_title}", header_format)
            sheet.write(row, 1, "Assigned Workload (Hrs)", header_format)
            row += 1
            labels = data.get('chart_labels', [])
            chart_data = data.get('chart_data', [])
            chart_details = data.get('chart_details', {})
            for i in range(len(labels)):
                lbl = labels[i]
                sheet.write(row, 0, lbl, text_format)
                sheet.write(row, 1, f"{chart_data[i]} Hrs", num_format)
                if detailed_excel and lbl in chart_details:
                    sheet.set_row(row, None, None, {'collapsed': True})
                    row += 1
                    for detail in chart_details[lbl]:
                        sheet.write(row, 0, f"   ↳ {detail['name']}", detail_text)
                        sheet.write(row, 1, f"{detail['hours']} Hrs", detail_num)
                        sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                        row += 1
                else:
                    row += 1
        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f"HR_Analytics_Export_{data.get('computed_end_date', fields.Date.today())}.xlsx",
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id