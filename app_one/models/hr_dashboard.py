from odoo import models, fields, api
from datetime import datetime, timedelta, date
import io
import base64
from dateutil.relativedelta import relativedelta
import calendar

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
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

    def dataframe(self, start_date, end_date, emp_ids):
        if not emp_ids:
            return []
        emp_fields = ['id', 'name', 'department_id', 'job_id', 'user_id', 'create_date', 'departure_date', 'active']
        employees = self.env['hr.employee'].with_context(active_test=False).search_read([('id', 'in', emp_ids)],
                                                                                        emp_fields)

        if not employees:
            return []

        user_to_emp = {e['user_id'][0]: e['id'] for e in employees if e['user_id']}
        user_ids = list(user_to_emp.keys())

        att_data = self.env['hr.attendance'].read_group(
            [('check_in', '>=', start_date), ('check_in', '<=', end_date), ('employee_id', 'in', emp_ids)],
            ['employee_id', 'worked_hours:sum'], ['employee_id'])
        att_map = {a['employee_id'][0]: (a.get('worked_hours', 0), a.get('__count', 0)) for a in att_data}

        leave_data = self.env['hr.leave'].read_group(
            [('state', '=', 'validate'), ('request_date_from', '>=', start_date), ('request_date_to', '<=', end_date),
             ('employee_id', 'in', emp_ids)], ['employee_id', 'number_of_days:sum'], ['employee_id'])
        leave_map = {l['employee_id'][0]: l.get('number_of_days', 0) for l in leave_data}

        sales_data = self.env['sale.order'].read_group(
            [('state', 'in', ['sale', 'done']), ('date_order', '>=', start_date), ('date_order', '<=', end_date),
             ('user_id', 'in', user_ids)], ['user_id', 'amount_total:sum'], ['user_id'])
        sales_map = {s['user_id'][0]: (s.get('amount_total', 0), s.get('__count', 0)) for s in sales_data}

        user_task_stats = {}
        if user_ids:
            task_groups = self.env['project.task'].read_group(
                [('create_date', '>=', start_date), ('create_date', '<=', end_date), ('user_ids', 'in', user_ids),
                 ('state', '!=', '1_canceled')],
                ['user_ids', 'allocated_hours:sum', 'state'],
                ['user_ids', 'state'], lazy=False
            )
            for tg in task_groups:
                uid_tuple = tg.get('user_ids')
                if uid_tuple and isinstance(uid_tuple, tuple):
                    uid = uid_tuple[0]
                    stats = user_task_stats.setdefault(uid, {'hrs': 0, 'done': 0, 'total': 0})
                    stats['hrs'] += tg.get('allocated_hours', 0.0)
                    stats['total'] += tg.get('__count', 0)
                    if tg.get('state') == '1_done':
                        stats['done'] += tg.get('__count', 0)

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
        return l

    @api.model
    def turnover_trend(self, start_date_val, end_date_val, department_id, search_query):
        trend_labels = []
        trend_data = []
        base_dom = ['|', ('active', '=', True), ('active', '=', False)]
        if department_id and str(department_id) != '0':
            base_dom.append(('department_id', '=', int(department_id)))
        if search_query:
            base_dom.append(('name', 'ilike', search_query))

        all_emps = self.env['hr.employee'].with_context(active_test=False).search_read(
            base_dom, ['create_date', 'departure_date', 'active']
        )

        months_cache = []
        current_month = start_date_val.replace(day=1)
        end_month = end_date_val.replace(day=1)

        while current_month <= end_month:
            target_month = current_month
            first_day = target_month.replace(day=1)
            last_day = target_month.replace(day=calendar.monthrange(target_month.year, target_month.month)[1])

            first_day_dt = datetime.combine(first_day, datetime.min.time())
            last_day_dt = datetime.combine(last_day, datetime.max.time())

            months_cache.append({
                'month_dt': target_month,
                'first_day_dt': first_day_dt,
                'last_day_dt': last_day_dt,
                'start_c': 0, 'end_c': 0, 'left_c': 0
            })
            current_month += relativedelta(months=1)

        for emp in all_emps:
            c_date = emp.get('create_date')
            d_date = emp.get('departure_date')
            is_active = emp.get('active')

            for m_data in months_cache:
                first_day_dt = m_data['first_day_dt']
                last_day_dt = m_data['last_day_dt']

                if c_date and c_date <= first_day_dt:
                    if is_active or (d_date and d_date >= first_day_dt.date()):
                        m_data['start_c'] += 1
                if c_date and c_date <= last_day_dt:
                    if is_active or (d_date and d_date > last_day_dt.date()):
                        m_data['end_c'] += 1
                if not is_active and d_date and first_day_dt.date() <= d_date <= last_day_dt.date():
                    m_data['left_c'] += 1

        for m_data in months_cache:
            start_c = m_data['start_c']
            end_c = m_data['end_c']
            left_c = m_data['left_c']
            avg = (start_c + end_c) / 2.0
            rate = round((left_c / avg) * 100, 2) if avg > 0 else 0
            trend_labels.append(m_data['month_dt'].strftime('%b %Y'))
            trend_data.append(rate)

        return {'labels': trend_labels, 'data': trend_data}

    @api.model
    def productivity_trend(self, start_date_val, end_date_val, department_id, search_query, active_filters):
        trend2_labels = []
        trend2_data = []
        active_filters = active_filters or {}
        active_emp = active_filters.get('active_emp', False)
        archived_emp = active_filters.get('archived_emp', False)

        emp_dom = []
        if archived_emp and not active_emp:
            emp_dom.append(('active', '=', False))
        elif active_emp and archived_emp:
            emp_dom.append(('active', 'in', [True, False]))
        else:
            emp_dom.append(('active', '=', True))

        if department_id and str(department_id) != '0':
            emp_dom.append(('department_id', '=', int(department_id)))
        if search_query:
            emp_dom.append(('name', 'ilike', search_query))

        employees = self.env['hr.employee'].with_context(active_test=False).search(emp_dom)
        u_ids = employees.mapped('user_id').ids

        if not u_ids:
            current_month = start_date_val.replace(day=1)
            end_month = end_date_val.replace(day=1)
            while current_month <= end_month:
                target_month = current_month
                trend2_labels.append(target_month.strftime('%b %Y'))
                trend2_data.append(0)
                current_month += relativedelta(months=1)
            return {'labels2': trend2_labels, 'data2': trend2_data}

        start_of_period = datetime.combine(start_date_val.replace(day=1), datetime.min.time())
        end_of_period = datetime.combine(
            end_date_val.replace(day=calendar.monthrange(end_date_val.year, end_date_val.month)[1]),
            datetime.max.time())

        months_cache2 = []
        agg_dict = {}
        if u_ids:
            tasks_agg = self.env['project.task'].read_group([
                ('user_ids', 'in', u_ids),
                ('create_date', '>=', start_of_period),
                ('create_date', '<=', end_of_period),
                ('state', '!=', '1_canceled')
            ], ['state'], ['create_date:month', 'state'], lazy=False)

            for agg in tasks_agg:
                m_key = agg.get('create_date:month')
                if not m_key: continue
                if m_key not in agg_dict:
                    agg_dict[m_key] = {'total': 0, 'done': 0}
                agg_dict[m_key]['total'] += agg.get('__count', 0)
                if agg.get('state') == '1_done':
                    agg_dict[m_key]['done'] += agg.get('__count', 0)

        current_month = start_date_val.replace(day=1)
        end_month = end_date_val.replace(day=1)
        while current_month <= end_month:
            target_month = current_month
            month_key = target_month.strftime('%B %Y')

            total_tasks = agg_dict.get(month_key, {}).get('total', 0)
            done_this_month = agg_dict.get(month_key, {}).get('done', 0)

            months_cache2.append({
                'month_dt': target_month,
                'total_tasks': total_tasks,
                'done_this_month': done_this_month
            })
            current_month += relativedelta(months=1)

        for m_data in months_cache2:
            total_tasks = m_data['total_tasks']
            done_this_month = m_data['done_this_month']
            if total_tasks > 0:
                productivity_rate = round((done_this_month / total_tasks * 100), 2)
            else:
                productivity_rate = 0
            trend2_labels.append(m_data['month_dt'].strftime('%b %Y'))
            trend2_data.append(productivity_rate)

        return {'labels2': trend2_labels, 'data2': trend2_data}

    @api.model
    def compute_kpis(self, *args, **kwargs):
        if args and isinstance(args[0], dict): kwargs.update(args[0])
        period = kwargs.get('period', '30')
        top_workload_limit = int(kwargs.get('top_workload', 5))
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
        filters = kwargs.get('filters', {})
        dept_id = filters.get('department_id')
        search = kwargs.get('search_query', '')
        group_by_list = kwargs.get('group_by_list', [])
        active_filters = kwargs.get('active_filters', {})
        active_emp = active_filters.get('active_emp', False)
        archived_emp = active_filters.get('archived_emp', False)
        emp_dom = []
        if archived_emp and not active_emp:
            emp_dom.append(('active', '=', False))
        elif active_emp and archived_emp:
            emp_dom.append(('active', 'in', [True, False]))
        else:
            emp_dom.append(('active', '=', True))

        if dept_id and str(dept_id) != '0':
            emp_dom.append(('department_id', '=', int(dept_id)))
        if search:
            emp_dom.append(('name', 'ilike', search))
        employees = self.env['hr.employee'].with_context(active_test=False).search(emp_dom)
        employee_count = len(employees)
        emp_ids = employees.ids
        u_ids = employees.mapped('user_id').ids
        user_emp_dict = {emp.user_id.id: emp for emp in employees if emp.user_id}
        tasks_done_count = self.env['project.task'].search_count(
            [('create_date', '>=', StartDate), ('create_date', '<=', EndDate), ('state', '=', '1_done'),
             ('user_ids', 'in', u_ids)]) if u_ids else 0
        total_tasks_for_kpi = self.env['project.task'].search_count(
            [('create_date', '>=', StartDate), ('create_date', '<=', EndDate), ('user_ids', 'in', u_ids),
             ('state', '!=', '1_canceled')]) if u_ids else 0

        workload_hours = 0
        chart_dict = {}
        chart_details = {}
        user_lbl_dict = {}
        for u_id, emp_rec in user_emp_dict.items():
            lbl = emp_rec.user_id.name if emp_rec and emp_rec.user_id else str(u_id)
            if group_by_list:
                parts = []
                for gb in group_by_list:
                    if gb == 'department':
                        parts.append(emp_rec.department_id.name or "No Dept")
                    elif gb == 'manager':
                        parts.append(emp_rec.parent_id.name or "No Mgr")
                    elif gb == 'job_position':
                        parts.append(emp_rec.job_id.name or "No Pos")
                if parts: lbl = " / ".join(parts)
            user_lbl_dict[u_id] = lbl
        if u_ids:
            workload_agg = self.env['project.task'].read_group([
                ('state', 'not in', ['1_done', '1_canceled']),
                ('create_date', '<=', EndDate),
                ('user_ids', 'in', u_ids)
            ], ['user_ids', 'allocated_hours:sum'], ['user_ids'], lazy=False)

            for agg in workload_agg:
                uid_tuple = agg.get('user_ids')
                if not uid_tuple: continue
                u = uid_tuple[0]
                if u not in u_ids: continue

                t_share = agg.get('allocated_hours', 0.0)
                workload_hours += t_share
                lbl = user_lbl_dict.get(u, str(u))
                chart_dict[lbl] = chart_dict.get(lbl, 0) + t_share
            limit_tasks = 5000
            offset_tasks = 0
            while True:
                tasks_todo = self.env['project.task'].search_read(
                    [('state', 'not in', ['1_done', '1_canceled']),
                     ('create_date', '<=', EndDate),
                     ('user_ids', 'in', u_ids)], ['name', 'allocated_hours', 'user_ids'], limit=limit_tasks,
                    offset=offset_tasks)
                if not tasks_todo: break

                for t in tasks_todo:
                    hours = t.get('allocated_hours', 0.0) or 0.0
                    users = t.get('user_ids', [])
                    t_share = hours / len(users) if users else hours
                    for u in users:
                        if u not in u_ids: continue
                        lbl = user_lbl_dict.get(u, str(u))
                        chart_details.setdefault(lbl, []).append(
                            {'name': t.get('name') or 'Task', 'hours': round(t_share, 2)})

                offset_tasks += limit_tasks
        actual_att_days = 0
        total_leaves = 0
        if emp_ids:
            att_agg = self.env['hr.attendance'].read_group(
                [('check_in', '>=', StartDate), ('check_in', '<=', EndDate), ('employee_id', 'in', emp_ids)],
                ['employee_id'], ['employee_id', 'check_in:day'], lazy=False)
            actual_att_days = len(att_agg)

            leaves_agg = self.env['hr.leave'].read_group(
                [('state', '=', 'validate'), ('request_date_to', '>=', start_date_val),
                 ('request_date_from', '<=', end_date_val), ('employee_id', 'in', emp_ids)], ['number_of_days:sum'], [])
            total_leaves = leaves_agg[0]['number_of_days'] if leaves_agg and leaves_agg[0]['number_of_days'] else 0
        expected_days = 0
        cal_counts = {}
        for e in employees:
            cal = e.resource_calendar_id or self.env.company.resource_calendar_id
            cal_counts[cal] = cal_counts.get(cal, 0) + 1

        for cal, count in cal_counts.items():
            hours_per_day = cal.hours_per_day or 8.0
            expected_days += (cal.get_work_hours_count(StartDate, EndDate) / hours_per_day) * count

        net_days = max(0, expected_days - total_leaves)
        attendance_rate = min((actual_att_days / net_days * 100), 100) if net_days > 0 else 0

        # ببعت ال emp_ids بعد الفتره للداتا فريم
        df = self.dataframe(start_date_val, end_date_val, emp_ids)
        dept_cards, scatter, workload_std, bottlenecks = [], [], 0.0, 0
        bottleneck_emp_ids = []
        labels3 = []
        means3 = []
        variances3 = []

        if df and len(df) > 0:
            allocated_hours_vals = [r['total_allocated_hours'] for r in df]
            completed_tasks_vals = [r['tasks_completed'] for r in df]
            n_rows = len(df)

            if n_rows > 1:
                m_h = sum(allocated_hours_vals) / n_rows
                m_d = sum(completed_tasks_vals) / n_rows
                variance = sum((x - m_h) ** 2 for x in allocated_hours_vals) / (n_rows - 1)
                workload_std = round(variance ** 0.5, 2)
            else:
                m_h = allocated_hours_vals[0]
                m_d = completed_tasks_vals[0]
            b_df = [r for r in df if r['total_allocated_hours'] > m_h and r['tasks_completed'] < m_d]
            bottlenecks = len(b_df)
            bottleneck_emp_ids = [r['id'] for r in b_df] if b_df else []
            for r in df:
                scatter.append(
                    {'x': round(r['total_allocated_hours'], 2), 'y': int(r['tasks_completed']), 'name': r['name']})
            dept_grouped = {}
            for r in df:
                if r['dept_name'] != 'Unknown':
                    d_n = r['dept_name']
                    if d_n not in dept_grouped:
                        dept_grouped[d_n] = {'prod_pcts': [], 'hours': [], 'total_tasks_dept': 0, 'done_tasks_dept': 0,
                                             'employees_details': []}
                    dept_grouped[d_n]['total_tasks_dept'] += r['total_tasks']
                    dept_grouped[d_n]['done_tasks_dept'] += r['tasks_completed']
                    dept_grouped[d_n]['prod_pcts'].append(r['productivity_pct'])
                    dept_grouped[d_n]['hours'].append(r['total_allocated_hours'])

                    dept_grouped[d_n]['employees_details'].append({
                        'name': r['name'],
                        'workload': r['total_allocated_hours'],
                        'productivity': r['productivity_pct']
                    })

            for d_n, vals in dept_grouped.items():
                g_len = len(vals['hours'])
                if vals['total_tasks_dept'] > 0:
                    prod_mean = round((vals['done_tasks_dept'] / vals['total_tasks_dept']) * 100, 2)
                else:
                    prod_mean = 0.0

                work_mean = sum(vals['hours']) / g_len if g_len > 0 else 0

                if g_len > 1:
                    # بحسب التباين لكل قسم لوحده
                    prod_var_raw = sum((x - prod_mean) ** 2 for x in vals['prod_pcts']) / (g_len - 1)
                    work_std_raw = (sum((x - work_mean) ** 2 for x in vals['hours']) / (g_len - 1)) ** 0.5
                else:
                    prod_var_raw = 0
                    work_std_raw = 0
                prod_std = prod_var_raw ** 0.5
                prod_var = round(prod_std, 2)
                work_std_pct = round((work_std_raw / work_mean * 100), 2) if work_mean > 0 else 0

                labels3.append(d_n)
                means3.append(prod_mean)
                variances3.append(prod_var)
                dept_cards.append({'department': d_n,
                                   'prod_mean': prod_mean,
                                   'work_std': work_std_pct,
                                   'prod_var': prod_var,
                                   'employees_details': vals['employees_details']})

        sorted_workload = sorted(chart_dict.items(), key=lambda item: item[1], reverse=True)[:top_workload_limit]
        final_chart_labels = [i[0] for i in sorted_workload]
        final_chart_data = [round(float(i[1]), 2) for i in sorted_workload]
        prod_trend_data = self.productivity_trend(start_date_val, end_date_val, dept_id, search, active_filters)
        turnover_res = self.turnover_trend(start_date_val, end_date_val, dept_id, search)
        base_dom_kpi = []
        if dept_id and str(dept_id) != '0':
            base_dom_kpi.append(('department_id', '=', int(dept_id)))
        if search:
            base_dom_kpi.append(('name', 'ilike', search))

        start_c_kpi = self.env['hr.employee'].with_context(active_test=False).search_count(
            base_dom_kpi + [('create_date', '<=', start_date_val), '|', ('active', '=', True),
                            ('departure_date', '>=', start_date_val)])
        end_c_kpi = self.env['hr.employee'].with_context(active_test=False).search_count(
            base_dom_kpi + [('create_date', '<=', end_date_val), '|', ('active', '=', True),
                            ('departure_date', '>', end_date_val)])
        left_c_kpi = self.env['hr.employee'].with_context(active_test=False).search_count(
            base_dom_kpi + [('active', '=', False), ('departure_date', '>=', start_date_val),
                            ('departure_date', '<=', end_date_val)])
        avg_kpi = (start_c_kpi + end_c_kpi) / 2.0
        emp_turnover_rate = round((left_c_kpi / avg_kpi) * 100, 2) if avg_kpi > 0 else 0

        return {
            'computed_start_date': str(start_date_val),
            'computed_end_date': str(end_date_val),
            'employee_count': employee_count,
            'workload_hours': round(workload_hours, 2),
            'tasks_complete': tasks_done_count,
            'production_kpi': round((tasks_done_count / total_tasks_for_kpi * 100),
                                    2) if total_tasks_for_kpi > 0 else 0,
            'chart_labels': final_chart_labels,
            'chart_data': final_chart_data,
            'anova_labels': labels3,
            'anova_means': means3,
            'anova_variances': variances3,
            'dept_stats_cards': dept_cards,
            'chart_details': chart_details,
            'trend_labels': turnover_res['labels'],
            'trend_data': turnover_res['data'],
            'prod_trend_labels': prod_trend_data['labels2'],
            'prod_trend_data': prod_trend_data['data2'],
            'attendance': round(attendance_rate, 2),
            'emp_turnover': emp_turnover_rate,
            'sales_per_emp': len(self.env['sale.order'].read_group(
                [('state', 'in', ['sale', 'done']), ('date_order', '>=', StartDate), ('date_order', '<=', EndDate),
                 ('user_id', 'in', u_ids)], ['user_id'], ['user_id'])) if u_ids else 0,
            'absence': round(max(100.0 - attendance_rate, 0.0), 2),
            'average_leaves': round((total_leaves / expected_days * 100), 2) if expected_days > 0 else 0,
            'departments': [{'id': d.id, 'name': d.name} for d in self.env['hr.department'].search([])],
            'workload_std': workload_std,
            'bottleneck_emps': bottlenecks,
            'bottleneck_emp_ids': bottleneck_emp_ids,
            'scatter_data': scatter,
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
            {'bold': True,'bg_color': '#17a2b8', 'font_color': 'white', 'border': 1, 'align': 'center',
             'valign': 'vcenter', 'size': 13})

        insight_header_format = workbook.add_format(
            {'bold': True, 'bg_color': '#17a2b8', 'font_color': 'white', 'border': 1, 'align': 'center',
             'valign': 'vcenter', 'size': 11})
        insight_text_format = workbook.add_format({'border': 1, 'align': 'left', 'font_size': 11})
        insight_num_format = workbook.add_format({'border': 1, 'align': 'center', 'font_size': 11})
        insight_pct_format = workbook.add_format(
            {'border': 1, 'align': 'center', 'font_size': 11, 'num_format': '0.00"%"'})

        text_format = workbook.add_format({'border': 1, 'align': 'left', 'font_size': 11})
        num_format = workbook.add_format({'border': 1, 'align': 'center', 'font_size': 11})
        detail_text = workbook.add_format(
            {'border': 1, 'indent': 1, 'font_color': '#475569', 'bg_color': '#f8fafc', 'font_size': 10})
        detail_num = workbook.add_format(
            {'border': 1, 'align': 'center', 'font_color': '#475569', 'bg_color': '#f8fafc', 'font_size': 10})

        sheet.set_column(0, 0, 35)
        sheet.set_column(1, 3, 20)

        dept_id = kwargs.get('filters', {}).get('department_id')
        dept_name = "All Departments"
        if dept_id and str(dept_id) != '0':
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

        row += 3
        dept_stats = data.get('dept_stats_cards', [])

        if dept_stats:
            sheet.write(row, 0, "Departmental Analytical Insights (ANOVA)", title_format)
            row += 1

            sheet.write(row, 0, "Department", insight_header_format)
            sheet.write(row, 1, "Avg Productivity", insight_header_format)
            sheet.write(row, 2, "Workload Inequality", insight_header_format)
            sheet.write(row, 3, "Performance Gap", insight_header_format)
            row += 1

            for dept in dept_stats:
                sheet.write(row, 0, dept.get('department', 'Unknown'), insight_text_format)
                sheet.write(row, 1, dept.get('prod_mean', 0), insight_pct_format)
                sheet.write(row, 2, dept.get('work_std', 0), insight_pct_format)
                sheet.write(row, 3, dept.get('prod_var', 0), insight_num_format)

                if detailed_excel and 'employees_details' in dept and dept['employees_details']:
                    sheet.set_row(row, None, None, {'collapsed': True})
                    row += 1
                    for emp_det in dept['employees_details']:
                        sheet.write(row, 0, f"   ↳ {emp_det['name']}", detail_text)
                        sheet.write(row, 1, emp_det['productivity'], detail_num)
                        sheet.write(row, 2, f"{emp_det['workload']} Hrs", detail_num)
                        sheet.write(row, 3, "-", detail_num)
                        sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                        row += 1
                else:
                    row += 1

            row += 2

            bottleneck_count = data.get('bottleneck_emps', 0)
            if bottleneck_count > 0:
                warning_format = workbook.add_format({'font_color': '#dc3545', 'bold': True, 'font_size': 10})
                sheet.write(row, 0,
                            f"* Critical Insight: Identified {bottleneck_count} employees as potential bottlenecks (High Workload, Low Completion).",
                            warning_format)

        row += 1

        note_header_format = workbook.add_format({
            'bold': True,
            'font_size': 12,
            'font_color': '#1f2937'

        })

        note_text_format = workbook.add_format({
            'font_size': 10,
            'text_wrap': True,
            'font_color': '#374151'
        })

        sheet.write(row, 0, "Insights Explanation", note_header_format)
        row += 1
        sheet.write(row, 0,
                    "Workload Inequality:\n"
                    "Measures workload balance inside departments.\n"
                    "Formula: (Workload Std Deviation ÷ Average Workload) × 100\n"
                    "Interpretation: Higher value = uneven workload distribution.",
                    note_text_format
                    )


        sheet.write(row, 1,
                    "Performance Gap:\n"
                    "Measures variation in employee productivity.\n"
                    "Formula: Standard Deviation of Productivity.\n"
                    "Interpretation: Higher value = bigger performance differences between employees.",
                    note_text_format
                    )
        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f"HR_Analytics_Export_{data.get('computed_end_date', fields.Date.today())}.xlsx",
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        return attachment.id