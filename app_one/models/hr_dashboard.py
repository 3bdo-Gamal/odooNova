from odoo import models, fields, api
class HR_Dashboard(models.Model):
    _name = 'wb.hr.dashboard'
    _description = 'HR KPI Dashboard'
    name = fields.Char(default="HR Dashboard")
    employee_count = fields.Integer(string='employee count')
    workload_hours = fields.Float(string="total workload hours")
    tasks_complete = fields.Integer(string=" tasks_complete")
    production_level_kpi = fields.Float(string="productivity")
    datajson = fields.Text()
    @api.model
    def compute_kpis(self):
        all_employees = self.env['hr.employee'].search([])
        done_tasks = self.env['project.task'].search([('state', 'in', ['1_done', '1_canceled'])])
        tasks_not_completed = self.env['project.task'].search([('state', 'not in', ['1_done', '1_canceled'])])
        employee_count = len(all_employees)
        # kpi number1
        tasks_complete = len(done_tasks)

        workload_hours = sum(task.allocated_hours for task in tasks_not_completed)
        # kpi number3
        if employee_count > 0:
            production_kpi = (tasks_complete / employee_count) * 100
        else:
            production_kpi = 0
        # kpi number5
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
        return {
            'employee_count': employee_count,
            'workload_hours': workload_hours,
            'tasks_complete': tasks_complete,
            'production_kpi': production_kpi,
            'chart_labels': list(employee_hours.keys()),
            'chart_data': [i for i in employee_hours.values()],
        }