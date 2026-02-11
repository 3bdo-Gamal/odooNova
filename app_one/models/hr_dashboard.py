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

    datajson = fields.Text()
    @api.model
    def compute_kpis(self,period=7):
        period = int(period)
        total_attendance = 0
        total_work = 0
        if (period == 0):
            period = 7
        datefilter = datetime.now()-timedelta(days=period)
        datefilter_date = datefilter.date()
        end_date = date.today()
        start_date = end_date - timedelta(days=period)
        all_employees = self.env['hr.employee'].search([])
        done_tasks = self.env['project.task'].search([('state', 'in', ['1_done', '1_canceled']),("create_date",">=",datefilter)])
        tasks_not_completed = self.env['project.task'].search([('state', 'not in', ['1_done', '1_canceled']),('create_date','>=',datefilter)])
        employee_count = len(all_employees)
        #2.emp.attendace
        for e in all_employees:
            attendances = self.env['hr.attendance'].search([
                ('employee_id','=',e.id),
                ('check_in','>=',datefilter),
            ])
            attendancesDays = len(attendances)
            leaves = self.env['hr.leave'].search([
                ('employee_id','=',e.id),
                ('state','=','validate'),
                ('request_date_to','>=',datefilter.date())
            ])
            leave_days = 0
            for leave in leaves:
                start_date = max(leave.request_date_from, datefilter_date)
                end_date = min(leave.request_date_to, date.today())
                if end_date >= start_date:
                    leave_days =leave_days+(end_date - start_date).days + 1
            total_attendance=total_attendance+len(attendances)
            Workdays = period - leave_days
            if (Workdays < 0):
                Workdays = 0
            total_work = total_work + Workdays
            days = total_attendance
            total_work_days = total_work
        if total_work > 0:
          attendance = round((total_attendance / total_work) * 100,2)
        else:
            attendance = 0

        #1.tasks compleleted
        tasks_complete = len(done_tasks)

        workload_hours = sum(task.allocated_hours for task in tasks_not_completed)
        # 3. productivity
        if employee_count > 0:
            production_kpi = (tasks_complete / employee_count) * 100
        else:
            production_kpi = 0
        # 5.workload
        employee_hours = {}
        for task in tasks_not_completed:
            hours = task.allocated_hours
            users = task.user_ids
            if not users:
                employee_hours['Unassigned'] = employee_hours.get('Unassigned', 0) + hours
            else:
                share = hours / len(users)
                for user in users:
                    employee_hours[user.name] = employee_hours.get(user.name, 0) + share
        emp_start_year = self.env['hr.employee'].search([('active', '=', True), ('create_date', '<=', start_date)])
        emp_end_year = self.env['hr.employee'].search([('active', '=', True), ('create_date', '<=', end_date)])
        emp_left = self.env['hr.employee'].search([('active','=',False),('write_date','>=',start_date),('write_date','<=',end_date)])
        avg_employees= (len(emp_start_year) + len(emp_end_year)) / 2
        if (avg_employees > 0):
            emp_turnover= round((len(emp_left) / avg_employees) * 100,2)
        else:
            emp_turnover = 0
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
        }
