/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
const { Component, onWillStart, onMounted, useState } = owl;

export class HrDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const today = new Date();
        const lastWeek = new Date(today);
        lastWeek.setDate(lastWeek.getDate() - 7);
        const formatDate = (date) => date.toISOString().split('T')[0];
        const todayStr = formatDate(today);
        const lastWeekStr = formatDate(lastWeek);
        const savedStartDate = sessionStorage.getItem("hr_dashboard_start") || lastWeekStr;
        const savedEndDate = sessionStorage.getItem("hr_dashboard_end") || todayStr;
        const savedDept = sessionStorage.getItem("hr_dashboard_dept") || null;
        this.state = useState({
            employee_count: 0,
            workload_hours: 0,
            tasks_complete: 0,
            production_kpi: 0,
            start_date: savedStartDate,
            end_date: savedEndDate,
            today_date: todayStr,
            filters: {
                department_id: savedDept,
            },
            kpis: {},
            departments: [],
        });
        this.last_valid_start = savedStartDate;
        this.last_valid_end = savedEndDate;

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.3.0/exceljs.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js");
            await this.downloaddata();
        });

        onMounted(() => {
            this.renderChart();
        });
    }

    async downloaddata() {
        try {
            const data = await this.orm.call("wb.hr.dashboard", "compute_kpis", [], {
                start_date: this.state.start_date,
                end_date: this.state.end_date,
                filters: this.state.filters
            });

            if (data) {
                this.state.employee_count = data.employee_count;
                this.state.workload_hours = data.workload_hours;
                this.state.tasks_complete = data.tasks_complete;
                this.state.production_kpi = data.production_kpi;
                this.state.attendance = data.attendance;
                this.state.emp_turnover = data.emp_turnover;
                this.state.sales_per_emp = data.sales_per_emp;
                this.state.departments = data.departments;
                this.chartLabels = data.chart_labels;
                this.chartData = data.chart_data;
                this.last_valid_start = this.state.start_date;
                this.last_valid_end = this.state.end_date;
            }
        } catch (e) {
            this.state.start_date = this.last_valid_start;
            this.state.end_date = this.last_valid_end;
            throw e;
        }
    }

    async onChangeStartDate(ev) {
        this.state.start_date = ev.target.value;
        sessionStorage.setItem("hr_dashboard_start", this.state.start_date);
        if (this.state.start_date && this.state.end_date) {
            await this.downloaddata();
            this.renderChart();
        }
    }

    async onChangeEndDate(ev) {
        this.state.end_date = ev.target.value;
        sessionStorage.setItem("hr_dashboard_end", this.state.end_date);
        if (this.state.start_date && this.state.end_date) {
            await this.downloaddata();
            this.renderChart();
        }
    }

    async onDepartmentChange(ev) {
        this.state.filters.department_id = ev.target.value || null;
        if (this.state.filters.department_id) {
            sessionStorage.setItem("hr_dashboard_dept", this.state.filters.department_id);
        } else {
            sessionStorage.removeItem("hr_dashboard_dept");
        }
        await this.downloaddata();
        this.renderChart();
    }

    showEmployees() {
        let domain = [];
        if (this.state.filters.department_id) {
            domain.push(['department_id', '=', parseInt(this.state.filters.department_id)]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Department Employees",
            res_model: "hr.employee",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    showWorkloadTasks() {
        let domain = [
            ['state', 'not in', ['1_done', '1_canceled']],
            ['create_date', '>=', this.state.start_date],
            ['create_date', '<=', this.state.end_date]
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Workload (Pending Tasks)",
            res_model: "project.task",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    showCompletedTasks() {
        let domain = [
            ['state', '=', '1_done'],
            ['create_date', '>=', this.state.start_date],
            ['create_date', '<=', this.state.end_date]
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Completed Tasks",
            res_model: "project.task",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    showAllTasks() {
        let domain = [
            ['create_date', '>=', this.state.start_date],
            ['create_date', '<=', this.state.end_date]
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "All Tasks (Productivity Analysis)",
            res_model: "project.task",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    showAttendances() {
        let domain = [
            ['check_in', '>=', this.state.start_date],
            ['check_in', '<=', this.state.end_date]
        ];
        if (this.state.filters.department_id) {
            domain.push(['employee_id.department_id', '=', parseInt(this.state.filters.department_id)]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Attendances Record",
            res_model: "hr.attendance",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    showTurnover() {
        let domain = [
            ['active', '=', false],
            ['departure_date', '>=', this.state.start_date],
            ['departure_date', '<=', this.state.end_date]
        ];
        if (this.state.filters.department_id) {
            domain.push(['department_id', '=', parseInt(this.state.filters.department_id)]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Left Employees (Turnover)",
            res_model: "hr.employee",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    showSales() {
        let domain = [
            ['state', 'in', ['sale', 'done']],
            ['date_order', '>=', this.state.start_date],
            ['date_order', '<=', this.state.end_date]
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Confirmed Sales",
            res_model: "sale.order",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    openChartTasks(employeeName) {
        let domain = [
            ['state', 'not in', ['1_done', '1_canceled']],
            ['create_date', '>=', this.state.start_date],
            ['create_date', '<=', this.state.end_date]
        ];
        if (employeeName === 'Unassigned') {
            domain.push(['user_ids', '=', false]);
        } else {
            domain.push(['user_ids.name', '=', employeeName]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Workload Details: ${employeeName}`,
            res_model: "project.task",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    async excelsheet() {
        let departmentName = "All Departments";
        if (this.state.filters.department_id) {
            const selectedDept = this.state.departments.find(d => d.id == this.state.filters.department_id);
            if (selectedDept) {
                departmentName = selectedDept.name;
            }
        }
        const workbook = new ExcelJS.Workbook();
        const worksheet = workbook.addWorksheet('HR Dashboard');
        worksheet.columns = [
            {width: 35},
            {width: 25}
        ];
        worksheet.addRow(["Department", departmentName]);
        worksheet.addRow(["From Date", this.state.start_date]);
        worksheet.addRow(["To Date", this.state.end_date]);
        worksheet.addRow([]);

        const headerRow = worksheet.addRow(["Key Performance Indicator", "Value"]);
        headerRow.eachCell((cell) => {
            cell.fill = {
                type: 'pattern',
                pattern: 'solid',
                fgColor: {argb: 'FF28A745'}
            };
            cell.font = {
                color: {argb: 'FFFFFFFF'},
                bold: true,
                size: 12
            };
        });
        worksheet.addRow(["Total Employees", this.state.employee_count]);
        worksheet.addRow(["Total Workload", this.state.workload_hours + " Hrs"]);
        worksheet.addRow(["Completed Tasks", this.state.tasks_complete]);
        worksheet.addRow(["Productivity", this.state.production_kpi + "%"]);
        worksheet.addRow(["Employee Attendances", this.state.attendance + "%"]);
        worksheet.addRow(["Employee Turnover", this.state.emp_turnover + "%"]);
        worksheet.addRow(["Sales Done/Employee", this.state.sales_per_emp]);
        worksheet.addRow([]);

        const chartHeaderRow = worksheet.addRow(["Workload Analysis", ""]);
        chartHeaderRow.getCell(1).font = {bold: true, color: {argb: 'FF007BFF'}};

        worksheet.addRow(["Employee Name", "Hours Assigned"]).font = {bold: true};

        if (this.chartLabels && this.chartData) {
            for (let i = 0; i < this.chartLabels.length; i++) {
                worksheet.addRow([this.chartLabels[i], this.chartData[i]]);
            }
        }
        const buffer = await workbook.xlsx.writeBuffer();
        const blob = new Blob([buffer], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "HR Analysis.xlsx";
        link.click();
    }

    async downloadPdf() {
        const {jsPDF} = window.jspdf;
        const doc = new jsPDF();
        let departmentName = "All Departments";
        if (this.state.filters.department_id) {
            const selectedDept = this.state.departments.find(d => d.id == this.state.filters.department_id);
            if (selectedDept) {
                departmentName = selectedDept.name;
            }
        }
        doc.setFontSize(22);
        doc.setTextColor(40, 167, 69);
        doc.text("HR Analysis ", 14, 20);
        doc.setFontSize(11);
        doc.setTextColor(50, 50, 50);
        doc.text(`Department: ${departmentName}`, 14, 30);
        doc.text(`From Date: ${this.state.start_date}      To Date: ${this.state.end_date}`, 14, 37);
        const kpiBody = [
            ["Total Employees", this.state.employee_count],
            ["Total Workload", this.state.workload_hours + " Hrs"],
            ["Completed Tasks", this.state.tasks_complete],
            ["Productivity", this.state.production_kpi + "%"],
            ["Employee Attendances", this.state.attendance + "%"],
            ["Employee Turnover", this.state.emp_turnover + "%"],
            ["Sales Done/Employee", this.state.sales_per_emp],
        ];
        doc.autoTable({
            startY: 45,
            head: [['Key Performance Indicator', 'Value']],
            body: kpiBody,
            headStyles: {fillColor: [40, 167, 69], fontSize: 12},
            styles: {fontSize: 11, cellPadding: 4},
            alternateRowStyles: {fillColor: [245, 245, 245]}
        });
        const chartBody = [];
        if (this.chartLabels && this.chartData) {
            for (let i = 0; i < this.chartLabels.length; i++) {
                chartBody.push([this.chartLabels[i], this.chartData[i] + " Hrs"]);
            }
        }
        if (chartBody.length > 0) {
            doc.autoTable({
                startY: doc.lastAutoTable.finalY + 15,
                head: [['Workload Analysis (Employee)', 'Hours Assigned']],
                body: chartBody,
                headStyles: {fillColor: [0, 123, 255], fontSize: 12},
                styles: {fontSize: 11, cellPadding: 4},
                alternateRowStyles: {fillColor: [245, 245, 245]}
            });
        }
        doc.save("HR Analysis.pdf");

    }

    renderChart() {
        const ctx = document.querySelector('.my_dashboard_chart');
        if (ctx && this.chartData) {
            if (ctx.chartInstance) ctx.chartInstance.destroy();
            const self = this;
            ctx.chartInstance = new window.Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: this.chartLabels,
                    datasets: [{
                        label: 'Hours',
                        data: this.chartData,
                        backgroundColor: ['#007bff', '#ffc107', '#28a745', '#6f42c1', '#17a2b8', '#e83e8c', '#fd7e14', '#20c997', '#0dcaf0', '#6c757d'],
                        hoverOffset: 10
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: (event, elements, chart) => {
                        if (elements && elements.length > 0) {
                            const clickedIndex = elements[0].index;
                            const clickedLabel = chart.data.labels[clickedIndex];
                            self.openChartTasks(clickedLabel);
                        }
                    },
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    }
                }
            });
        }
    }
}
HrDashboard.template = "HRdashboard";
registry.category("actions").add("hr_dashboard_client_tag", HrDashboard);