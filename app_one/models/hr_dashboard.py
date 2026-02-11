from odoo import models, fields, api
from datetime import datetime,timedelta,date
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
    emp_turnover=fields.Float(string=' Employee TurnOver ')
    sales_per_emp=fields.Integer(string=" Sales of Employees")

    datajson = fields.Text()
    @api.model
    def compute_kpis(self,period=7):
        period = int(period)
        total_attendance = 0
        total_work = 0
        if (period == 0):
            period = 7
        datefilter = datetime.now() - timedelta(days=period)
        datefilter_date = datefilter.date()
        today_date = date.today()
        end_date = date.today()
        start_date = end_date - timedelta(days=period)
        employee_count = self.env['hr.employee'].search_count([])
        # 1.tasks complete
        tasks_complete = self.env['project.task'].search_count(
            [('state', 'in', ['1_done', '1_canceled']), ("create_date", ">=", datefilter)])
        tasks_not_completed = self.env['project.task'].search(
            [('state', 'not in', ['1_done', '1_canceled']), ('create_date', '>=', datefilter)])
        # 2.emp attandance
        total_attendance = self.env['hr.attendance'].search_count([('check_in', '>=', datefilter)])
        days = total_attendance
        leaves = self.env['hr.leave'].search([('state', '=', 'validate'), ('request_date_to', '>=', datefilter_date), ('request_date_from', '<=', today_date)])
        total_leave_days = 0
        for leave in leaves:
            start_d = max(leave.request_date_from, datefilter_date)
            end_d = min(leave.request_date_to, today_date)
            if (end_d >= start_d):
                total_leave_days = total_leave_days + (end_d - start_d).days + 1
        total_work = (employee_count * period) - total_leave_days
        if (total_work < 0):
            total_work = 0
        total_work_days = total_work
        if (total_work > 0):
            attendance = round((total_attendance / total_work) * 100, 2)
        else:
            attendance = 0
        workload_data = self.env['project.task'].read_group(domain=[('state', 'not in', ['1_done', '1_canceled']), ('create_date', '>=', datefilter)],fields=['allocated_hours'], groupby=[])
        if (workload_data):
            workload_hours = workload_data[0]['allocated_hours']
        else:
            workload_hours = 0
        # 3.Productivity
        if (employee_count > 0):
            production_kpi = (tasks_complete / employee_count) * 100
        else:
            production_kpi = 0
            # workload
        employee_hours = {}
        for task in tasks_not_completed:
            hours = task.allocated_hours
            users = task.user_ids
            if not users:
                employee_hours['Unassigned'] = employee_hours.get('Unassigned', 0) + hours
            else:
                t_share = hours / len(users)
                for user in users:
                    employee_hours[user.name] = employee_hours.get(user.name, 0) + t_share
        # 6.emp turnover
        emp_start_year = self.env['hr.employee'].search_count([('active', '=', True), ('create_date', '<=', start_date)])
        emp_end_year = self.env['hr.employee'].search_count([('active', '=', True), ('create_date', '<=', end_date)])
        emp_left = self.env['hr.employee'].search_count([('active', '=', False), ('write_date', '>=', start_date), ('write_date', '<=', end_date)])
        avg_employees = (emp_start_year + emp_end_year) / 2
        if (avg_employees > 0):
            emp_turnover = round((emp_left / avg_employees) * 100, 2)
        else:
            emp_turnover = 0
        sales_per_emp = self.env['sale.order'].read_group(domain=[('state', 'in', ['sale', 'done']), ('date_order', '>=', datefilter)], fields=['amount_total:sum'],groupby=['user_id'])
        sales_per_emp = len(sales_per_emp)
        return {
        'employee_count': employee_count,
        'workload_hours': workload_hours,
        'tasks_complete': tasks_complete,
        'production_kpi': production_kpi,
        'chart_labels': list(employee_hours.keys()),
        'chart_data': [i for i in employee_hours.values()],
        'days': days,
        'attendance': attendance,
        'total_work_days': total_work_days,
        'emp_turnover': emp_turnover,
        'sales_per_emp': sales_per_emp,
       }
