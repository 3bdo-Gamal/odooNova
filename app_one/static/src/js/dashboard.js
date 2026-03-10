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
       const savedDeptStr = sessionStorage.getItem("hr_dashboard_dept");
        const savedDept = savedDeptStr ? parseInt(savedDeptStr) : "";

        const savedFavorites = JSON.parse(localStorage.getItem('hr_dashboard_favorites')) || [];
        const defaultFav = savedFavorites.find(f => f.is_default === true);

        this.state = useState({
            showSidebar: true,
            employee_count: 0,
            workload_hours: 0,
            tasks_complete: 0,
            production_kpi: 0,
            average_leaves:0,
            absence:0,
            start_date: savedStartDate,
            end_date: savedEndDate,
            today_date: todayStr,
            filters: {
                department_id: savedDept,
            },
            kpis: {},
            departments: [],

            search_query: defaultFav ? defaultFav.search_query : '',
            active_filters: defaultFav ? { ...defaultFav.active_filters } : { active_emp: false, archived_emp: false },
            group_by_list: defaultFav ? [...defaultFav.group_by_list] : [],
            active_favorite_name: defaultFav ? defaultFav.name : null,
            saved_favorites: savedFavorites,
            show_save_menu: false,
            favorite_name: 'HR Analytics',
            is_default_fav: false,
            is_shared_fav: false,
            showExportModal: false,
            export_group: 'department',
            meas_emp: true,
            meas_workload: true,
            meas_tasks: true,
            meas_prod: true,
            meas_att: false,
            meas_turnover: false,
            meas_sales: false,
            meas_leaves: false,
            meas_absence:false,
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

    toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
    }

    async downloaddata() {
        try {
            const data = await this.orm.call("wb.hr.dashboard", "compute_kpis", [], {
                start_date: this.state.start_date,
                end_date: this.state.end_date,
                filters: this.state.filters,
                search_query: this.state.search_query,
                active_filters: this.state.active_filters,
                group_by_list: this.state.group_by_list
            });

            if (data) {
                this.state.employee_count = data.employee_count;
                this.state.workload_hours = data.workload_hours;
                this.state.tasks_complete = data.tasks_complete;
                this.state.production_kpi = data.production_kpi;
                this.state.attendance = data.attendance;
                this.state.emp_turnover = data.emp_turnover;
                this.state.sales_per_emp = data.sales_per_emp;
                this.state.average_leaves=data.average_leaves;
                this.state.absence=data.absence;
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
        this.state.filters.department_id = ev.target.value ? parseInt(ev.target.value) : "";

        if (this.state.filters.department_id) {
            sessionStorage.setItem("hr_dashboard_dept", this.state.filters.department_id);
        } else {
            sessionStorage.removeItem("hr_dashboard_dept");
        }
        await this.downloaddata();
        this.renderChart();
    }
    async onSearchKeyUp(ev) {
        if (ev.key === 'Enter' && ev.target.value.trim() !== '') {
            this.state.active_favorite_name = null;
            this.state.search_query = ev.target.value;
            ev.target.value = '';
            await this.downloaddata();
            this.renderChart();
        }
    }

    async clearSearchQuery() {
        this.state.active_favorite_name = null;
        this.state.search_query = '';
        await this.downloaddata();
        this.renderChart();
    }

    async toggleFilter(filterName) {
        this.state.active_favorite_name = null;
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
        if (filterName === 'active_emp' && this.state.active_filters.active_emp) {
            this.state.active_filters.archived_emp = false;
        } else if (filterName === 'archived_emp' && this.state.active_filters.archived_emp) {
            this.state.active_filters.active_emp = false;
        }

        await this.downloaddata();
        this.renderChart();
    }

    async toggleGroupBy(groupName) {
        this.state.active_favorite_name = null;
        if (this.state.group_by_list.includes(groupName)) {
            this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        } else {
            this.state.group_by_list.push(groupName);
        }
        await this.downloaddata();
        this.renderChart();
    }

    async removeGroupBy(groupName) {
        this.state.active_favorite_name = null;
        this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        await this.downloaddata();
        this.renderChart();
    }

    toggleSaveMenu(ev) {
        ev.stopPropagation();
        this.state.show_save_menu = !this.state.show_save_menu;
    }
    onDefaultCheckboxChange() {
        if (this.state.is_default_fav) {
            this.state.is_shared_fav = false;
        }
    }
    onSharedCheckboxChange() {
        if (this.state.is_shared_fav) {
            this.state.is_default_fav = false;
        }
    }

    saveFavoriteUI(ev) {
        ev.stopPropagation();
        if (this.state.favorite_name.trim()) {
            if (this.state.is_default_fav) {
                this.state.saved_favorites.forEach(f => f.is_default = false);
            }

            const newFav = {
                id: Date.now(),
                name: this.state.favorite_name,
                search_query: this.state.search_query,
                active_filters: { ...this.state.active_filters },
                group_by_list: [...this.state.group_by_list],
                is_default: this.state.is_default_fav,
                is_shared: this.state.is_shared_fav
            };

            this.state.saved_favorites.push(newFav);
            localStorage.setItem('hr_dashboard_favorites', JSON.stringify(this.state.saved_favorites));

            this.state.show_save_menu = false;
            this.state.favorite_name = 'HR Analytics Overview';
            this.state.is_default_fav = false;
            this.state.is_shared_fav = false;
        }
    }

    loadFavorite(fav) {
        this.state.search_query = fav.search_query;
        this.state.active_filters = { ...fav.active_filters };
        this.state.group_by_list = [...fav.group_by_list];
        this.state.active_favorite_name = fav.name;
        this.downloaddata();
        this.renderChart();
    }
    async clearFavorite() {
        this.state.active_favorite_name = null;
        this.state.search_query = '';
        this.state.active_filters = { active_emp: true, archived_emp: false };
        this.state.group_by_list = [];
        await this.downloaddata();
        this.renderChart();
    }

    deleteFavorite(favId) {
        this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== favId);
        localStorage.setItem('hr_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
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
     showleaves(){
        let domain=[['state', '=', 'validate'],
            ['request_date_to', '>=', this.state.start_date],
            ['request_date_from', '<=', this.state.end_date]];
        if (this.state.filters.department_id){
            domain.push(['employee_id.department_id',"=",parseInt(this.state.filters.department_id)]);
        }
        this.action.doAction({
            type:'ir.actions.act_window',
            name:"Leaves Record",
            res_model:'hr.leave',
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,

        })
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
    showAbsence() {
        let domain = [
            ['attendance_ids', '=', false],
            ['leave_manager_id', '!=', false],
        ];
        if (this.state.filters.department_id) {
            domain.push(['department_id', '=', parseInt(this.state.filters.department_id)]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Absence Analysis",
            res_model: "hr.employee",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
            context: { 'search_default_filter_to_check': 1 }
        });
    }
    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }

    async downloadCustomExcel() {
        if (!this.state.meas_emp && !this.state.meas_workload && !this.state.meas_tasks &&
            !this.state.meas_prod && !this.state.meas_att && !this.state.meas_turnover &&
            !this.state.meas_sales && !this.state.meas_leaves && !this.state.meas_absence) {
            alert("Please select at least one KPI to export.");
            return;
        }
        this.state.showExportModal = false;
        let exportGroupBy = [];
        if (this.state.export_group !== 'none') {
            exportGroupBy.push(this.state.export_group);
        }

        const data = await this.orm.call("wb.hr.dashboard", "compute_kpis", [], {
            start_date: this.state.start_date,
            end_date: this.state.end_date,
            filters: this.state.filters,
            search_query: this.state.search_query,
            active_filters: this.state.active_filters,
            group_by_list: exportGroupBy
        });
        const workbook = new ExcelJS.Workbook();
        const worksheet = workbook.addWorksheet('HR Pivot Data');
        worksheet.columns = [ {width: 35}, {width: 25} ];
        let deptName = "All Departments";
        if (this.state.filters.department_id) {
            const selectedDept = this.state.departments.find(d => d.id == this.state.filters.department_id);
            if (selectedDept) deptName = selectedDept.name;
        }
        worksheet.addRow(["Department Filter", deptName]);
        worksheet.addRow(["From Date", this.state.start_date]);
        worksheet.addRow(["To Date", this.state.end_date]);
        if (this.state.search_query) worksheet.addRow(["Employee Name", this.state.search_query]);
        worksheet.addRow([]);

        const headerRow = worksheet.addRow(["Key Performance Indicator", "Value"]);
        headerRow.eachCell((cell) => {
            cell.fill = { type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'} };
            cell.font = { color: {argb: 'FFFFFFFF'}, bold: true, size: 13 };
        });

        if (this.state.meas_emp) worksheet.addRow(["Total Employees", data.employee_count]);
        if (this.state.meas_workload) worksheet.addRow(["Total Workload", data.workload_hours + " Hrs"]);
        if (this.state.meas_tasks) worksheet.addRow(["Completed Tasks", data.tasks_complete]);
        if (this.state.meas_prod) worksheet.addRow(["Productivity", data.production_kpi + "%"]);
        if (this.state.meas_att) worksheet.addRow(["Employee Attendances", data.attendance + "%"]);
        if (this.state.meas_turnover) worksheet.addRow(["Employee Turnover", data.emp_turnover + "%"]);
        if (this.state.meas_sales) worksheet.addRow(["Sales Done/Employee", data.sales_per_emp]);
        if (this.state.meas_leaves) worksheet.addRow(["Vacations Rate", data.average_leaves + "%"]);
        if (this.state.meas_absence) worksheet.addRow(["Absence Rate", data.absence + "%"]);

        worksheet.addRow([]);
        if (this.state.export_group !== 'none') {
            const chartHeaderRow = worksheet.addRow([`Workload Analysis by: ${this.state.export_group.replace('_', ' ').toUpperCase()}`, ""]);
            chartHeaderRow.getCell(1).font = {bold: true, color: {argb: '17ac39'},size:10};
            worksheet.addRow(["Group By", "Assigned Workload (Hrs)"]).font = {bold: true};

            if (data.chart_labels && data.chart_data) {
                for (let i = 0; i < data.chart_labels.length; i++) {
                    worksheet.addRow([data.chart_labels[i], data.chart_data[i]]);
                }
            }
        }
        const buffer = await workbook.xlsx.writeBuffer();
        const blob = new Blob([buffer], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `HR_Analytics_Report${this.state.today_date}.xlsx`;
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
        doc.setTextColor(0, 123, 255);
        doc.text("HR Analysis", 14, 20);

        doc.setFontSize(11);
        doc.setTextColor(50, 50, 50);
        let currentY = 30;
        doc.text(`Department: ${departmentName}`, 14, currentY);
        currentY += 7;
        doc.text(`From Date: ${this.state.start_date}      To Date: ${this.state.end_date}`, 14, currentY);
        currentY += 7;
        if (this.state.search_query) {
            doc.text(`Employee Name: ${this.state.search_query}`, 14, currentY);
            currentY += 7;
        }

        const kpiBody = [
            ["Total Employees", this.state.employee_count],
            ["Total Workload", this.state.workload_hours + " Hrs"],
            ["Completed Tasks", this.state.tasks_complete],
            ["Productivity", this.state.production_kpi + "%"],
            ["Employee Attendances", this.state.attendance + "%"],
            ["Employee Turnover", this.state.emp_turnover + "%"],
            ["Sales Done/Employee", this.state.sales_per_emp],
            ["Employee Vocations", this.state.average_leaves + "%"],
            ["Employee absenteeism", this.state.absence + "%"],
        ];
        doc.autoTable({
            startY: currentY + 3,
            head: [['Key Performance Indicator', 'Value']],
            body: kpiBody,
            headStyles: {fillColor: [0, 123, 255], fontSize: 12},
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
            let groupByTitle = 'Employee';
            if (this.state.group_by_list && this.state.group_by_list.length > 0) {
                groupByTitle = this.state.group_by_list.map(g => g.replace('_', ' ').toUpperCase()).join(' / ');
            }

            doc.autoTable({
                startY: doc.lastAutoTable.finalY + 15,
                head: [[`Workload Analysis (${groupByTitle})`, 'Hours Assigned']],
                body: chartBody,
                headStyles: {fillColor: [0, 123, 255], fontSize: 12},
                styles: {fontSize: 11, cellPadding: 4},
                alternateRowStyles: {fillColor: [245, 245, 245]}
            });
        }
        doc.save(`HR_Analysis_${this.state.today_date}.pdf`);
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