from odoo import models, fields, api
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError
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
    datajson = fields.Text()

    @api.model
    def compute_kpis(self, start_date=None, end_date=None, **kwargs):

        if isinstance(start_date, str) and start_date:
            StartDate = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            StartDate = datetime.now() - timedelta(days=7)

        if isinstance(end_date, str) and end_date:
            EndDate = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        else:
            EndDate = datetime.now()
        today = date.today()
        start_date = StartDate.date()
        end_date = EndDate.date()
        if end_date > today or start_date > today:
            raise UserError("Not Valid Date: You should enter a date less than or equal to today.")

        if start_date > end_date:
            raise UserError("Not Valid Date: end date cannot be less than start date.")

        datefilter = StartDate
        datefilter_date = StartDate.date()
        today_date = EndDate.date()
        start_date_val = StartDate.date()
        end_date_val = EndDate.date()

        departments = self.env['hr.department'].search([])
        filters = kwargs.get('filters', {}) or self.env.context.get('filters', {})
        department_id = filters.get('department_id')
        #all domain
        employee_domain = []
        domain_tasks_complete = [('state', '=', '1_done'), ('create_date', '>=', datefilter), ('create_date', '<=', EndDate)]
        domain_tasks_not_complete = [('state', 'not in', ['1_done', '1_canceled']), ('create_date', '>=', datefilter), ('create_date', '<=', EndDate)]
        domain_attendance = [('check_in', '>=', datefilter), ('check_in', '<=', EndDate)]
        domain_leaves = [('state', '=', 'validate'), ('request_date_to', '>=', datefilter_date), ('request_date_from', '<=', today_date)]
        domain_calendars = [('active', '=', True)]

        domain_emp_start = [('create_date', '<=', start_date_val), '|', ('active', '=', True), ('departure_date', '>=', start_date_val)]
        domain_emp_end = [('create_date', '<=', end_date_val), '|', ('active', '=', True), ('departure_date', '>', end_date_val)]
        domain_emp_left = [('active', '=', False), ('departure_date', '>=', start_date_val), ('departure_date', '<=', end_date_val)]

        domain_sales = [('state', 'in', ['sale', 'done']), ('date_order', '>=', datefilter), ('date_order', '<=', EndDate)]
         #dep_filter
        if department_id:
            department_id = int(department_id)
            employees_in_dept = self.env['hr.employee'].search([('department_id', '=', department_id)])
            dept_emp_ids = employees_in_dept.ids if employees_in_dept else [-1]
            dept_user_ids = employees_in_dept.mapped('user_id').ids if employees_in_dept.mapped('user_id') else [-1]

            employee_domain.append(('department_id', '=', department_id))
            domain_emp_start.append(('department_id', '=', department_id))
            domain_emp_end.append(('department_id', '=', department_id))
            domain_emp_left.append(('department_id', '=', department_id))

            domain_attendance.append(('employee_id', 'in', dept_emp_ids))
            domain_leaves.append(('employee_id', 'in', dept_emp_ids))
            domain_calendars.append(('id', 'in', dept_emp_ids))

            domain_tasks_complete.append(('user_ids', 'in', dept_user_ids))
            domain_tasks_not_complete.append(('user_ids', 'in', dept_user_ids))

            domain_sales.append(('user_id', 'in', dept_user_ids))

        employee_count = self.env['hr.employee'].search_count(employee_domain)
         #kpi attendance
        total_attendance = self.env['hr.attendance'].read_group(domain=domain_attendance, fields=['employee_id'], groupby=['employee_id', 'check_in:day'], lazy=False)
        actual_attendance_days = len(total_attendance)

        leaves = self.env['hr.leave'].read_group(domain=domain_leaves, fields=['number_of_days:sum'], groupby=[])
        total_leave_days = float(leaves[0].get('number_of_days') or 0.0) if leaves else 0.0

        employee_calendars = self.env['hr.employee'].read_group(domain=domain_calendars, fields=['resource_calendar_id'], groupby=['resource_calendar_id'])
        total_expected_company_days = 0.0

        for group in employee_calendars:
            emp_count = group.get('resource_calendar_id_count') or group.get('__count', 0)
            calendar_id = group.get('resource_calendar_id')
            if calendar_id:
                calendar = self.env['resource.calendar'].browse(calendar_id[0])
            else:
                calendar = self.env.company.resource_calendar_id

            expected_hours = calendar.get_work_hours_count(datefilter, EndDate)
            hours_per_day = calendar.hours_per_day or 8.0
            expected_days_per_emp = expected_hours / hours_per_day
            total_expected_company_days += (expected_days_per_emp * emp_count)

        net_expected_days = max(0, total_expected_company_days - total_leave_days)
        total_percentage = 0
        if net_expected_days > 0:
            total_percentage = (actual_attendance_days / net_expected_days) * 100
        attendance = min(round(total_percentage, 2), 100.0)
        workload_data = None
        workload_hours = 0.0
        #kpi tasks complete
        tasks_complete = self.env['project.task'].search_count(domain_tasks_complete)
        tasks_not_completed = self.env['project.task'].search(domain_tasks_not_complete)
        tasks_all = tasks_complete + len(tasks_not_completed)
        # kpi productivity
        production_kpi = (tasks_complete / tasks_all) * 100 if tasks_all else 0.0
        # kpi workload
        employee_hours = {}
        for task in tasks_not_completed:
            hours = task.allocated_hours or 0.0
            users = task.user_ids
            if not users:
                if not department_id:
                    employee_hours['Unassigned'] = employee_hours.get('Unassigned', 0.0) + hours
                    workload_hours += hours
            else:
                t_share = hours / len(users)
                for user in users:
                    if not department_id or user.id in dept_user_ids:
                        employee_hours[user.name] = employee_hours.get(user.name, 0.0) + t_share
                        workload_hours += t_share
        #kpi turnover
        emp_start_year = self.env['hr.employee'].search_count(domain_emp_start)
        emp_end_year = self.env['hr.employee'].search_count(domain_emp_end)
        emp_left = self.env['hr.employee'].search_count(domain_emp_left)
        avg_employees = (emp_start_year + emp_end_year) / 2
        emp_turnover = round((emp_left / avg_employees) * 100, 2) if avg_employees > 0 else 0.0
         #kpi sales/emp
        sales_per_emp_data = self.env['sale.order'].read_group(domain=domain_sales, fields=['amount_total:sum'], groupby=['user_id'])
        sales_per_emp = len(sales_per_emp_data)

        return {
            'employee_count': int(employee_count ),
            'workload_hours': round(float(workload_hours), 2),
            'tasks_complete': int(tasks_complete),
            'production_kpi': round(float(production_kpi), 2),
            'chart_labels': list(employee_hours.keys()),
            'chart_data': [round(float(i), 2) for i in employee_hours.values()],
            'attendance': round(float(attendance), 2),
            'emp_turnover': round(float(emp_turnover ), 2),
            'sales_per_emp': int(sales_per_emp),
            'departments': [{'id': d.id, 'name': d.name} for d in departments],

        }