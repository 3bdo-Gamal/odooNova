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
        const formatDate = (date) => date.toISOString().split('T')[0];
        const todayStr = formatDate(today);

        const savedPeriod = sessionStorage.getItem("hr_dashboard_period") || "30";
        const savedStartDate = sessionStorage.getItem("hr_dashboard_start") || "";
        const savedEndDate = sessionStorage.getItem("hr_dashboard_end") || "";
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
            average_leaves: 0,
            absence: 0,
            bottleneck_emps: 0,
            bottleneck_emp_ids: [],
            workload_std: 0,
            dept_stats_cards: [],
            period: savedPeriod,
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
            detailed_excel: false,
            meas_emp: true,
            meas_workload: true,
            meas_tasks: false,
            meas_prod: false,
            meas_att: false,
            meas_turnover: false,
            meas_sales: false,
            meas_leaves: false,
            meas_absence: false,
            showPdfModal: false,
            pdf_emp: true,
            pdf_workload: true,
            pdf_att: true,
            pdf_sales: false,
            prod_trend_labels: [],
            prod_trend_data: [],
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
        if (this.state.period === "0" || this.state.period === 0) {
            if (this.state.start_date && this.state.end_date) {
                const start = new Date(this.state.start_date);
                const end = new Date(this.state.end_date);
                const td = new Date(this.state.today_date);
                if (start > end || start > td || end > td) {
                    alert("Invalid Date Range! Reverting to last valid dates.");
                    this.state.start_date = this.last_valid_start;
                    this.state.end_date = this.last_valid_end;
                    sessionStorage.setItem("hr_dashboard_start", this.last_valid_start || "");
                    sessionStorage.setItem("hr_dashboard_end", this.last_valid_end || "");
                    return;
                }
            }
        }

        try {
            const data = await this.orm.call("wb.hr.dashboard", "compute_kpis", [], {
                period: this.state.period,
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
                this.state.average_leaves = data.average_leaves;
                this.state.absence = data.absence;
                this.state.departments = data.departments;

                this.state.bottleneck_emps = data.bottleneck_emps;
                this.state.bottleneck_emp_ids = data.bottleneck_emp_ids || [];
                this.state.workload_std = data.workload_std;
                this.state.dept_stats_cards = data.dept_stats_cards;

                this.chartLabels = data.chart_labels;
                this.chartData = data.chart_data;
                this.trendLabels = data.trend_labels;
                this.trendData = data.trend_data;
                this.scatterData = data.scatter_data;
                this.state.prod_trend_labels = data.prod_trend_labels;
                this.state.prod_trend_data = data.prod_trend_data;
                this.anovaLabels = data.anova_labels || [];
                this.anovaMeans = data.anova_means || [];
                this.anovaVariances = data.anova_variances || [];
                if (data.computed_start_date && data.computed_end_date) {
                    this.state.start_date = data.computed_start_date;
                    this.state.end_date = data.computed_end_date;
                }

                this.last_valid_start = this.state.start_date;
                this.last_valid_end = this.state.end_date;

                sessionStorage.setItem("hr_dashboard_start", this.state.start_date);
                sessionStorage.setItem("hr_dashboard_end", this.state.end_date);
            }
        } catch (e) {
            this.state.start_date = this.last_valid_start;
            this.state.end_date = this.last_valid_end;
            sessionStorage.setItem("hr_dashboard_start", this.last_valid_start || "");
            sessionStorage.setItem("hr_dashboard_end", this.last_valid_end || "");
            throw e;
        }
    }

    async onChangePeriod(ev) {
        this.state.period = ev.target.value;
        sessionStorage.setItem("hr_dashboard_period", this.state.period);
        this.state.start_date = "";
        this.state.end_date = "";
        sessionStorage.removeItem("hr_dashboard_start");
        sessionStorage.removeItem("hr_dashboard_end");
        await this.downloaddata();
        this.renderChart();
    }

    async onChangeStartDate(ev) {
        this.state.start_date = ev.target.value;
        if (this.state.start_date && this.state.end_date) {
            this.state.period = "0";
            sessionStorage.setItem("hr_dashboard_period", "0");
            await this.downloaddata();
            this.renderChart();
        }
    }

    async onChangeEndDate(ev) {
        this.state.end_date = ev.target.value;
        if (this.state.start_date && this.state.end_date) {
            this.state.period = "0";
            sessionStorage.setItem("hr_dashboard_period", "0");
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

    openEmployeeAllTasks(employeeName) {
        let domain = [
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
            name: `Analysis for: ${employeeName}`,
            res_model: "project.task",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    openTrendDetails(monthLabel, datasetIndex) {
        const date = new Date(monthLabel + " 1");
        const startStr = date.toISOString().split('T')[0];
        const endStr = new Date(date.getFullYear(), date.getMonth() + 1, 0).toISOString().split('T')[0];

        let domain = [];
        let res_model = "";
        let name = "";

        if (datasetIndex === 0) {
            res_model = "project.task";
            name = `Completed Tasks (${monthLabel})`;
            domain = [
                ['state', '=', '1_done'],
                ['date_last_stage_update', '>=', startStr],
                ['date_last_stage_update', '<=', endStr]
            ];
        } else if (datasetIndex === 1) {
            res_model = "hr.employee";
            name = `Turnover Employees (${monthLabel})`;
            domain = [
                ['active', '=', false],
                ['departure_date', '>=', startStr],
                ['departure_date', '<=', endStr]
            ];
            if (this.state.filters.department_id) {
                domain.push(['department_id', '=', parseInt(this.state.filters.department_id)]);
            }
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: res_model,
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }

    openDepartmentEmployees(deptName) {
        let domain = [['department_id.name', '=', deptName]];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Employees in: ${deptName}`,
            res_model: "hr.employee",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }
    showWorkloadCongestion() {
        let domain = [];
        const emp_ids = Array.from(this.state.bottleneck_emp_ids || []);

        if (emp_ids.length > 0) {
            domain.push(['id', 'in', emp_ids]);
        } else {
            domain.push(['id', '=', -1]);
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Bottleneck Employees",
            res_model: "hr.employee",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
        });
    }
showWorkloadDisparity() {
        let domain = [
            ['state', 'not in', ['1_done', '1_canceled']],
            ['create_date', '>=', this.state.start_date],
            ['create_date', '<=', this.state.end_date]
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Workload Disparity Analysis",
            res_model: "project.task",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
            context: { 'group_by': ['user_ids'] }
        });
    }
    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    openPdfModal() { this.state.showPdfModal = true; }
    closePdfModal() { this.state.showPdfModal = false; }

    async downloadCustomExcel() {
        const measures = [];
        if (this.state.meas_emp) measures.push('emp');
        if (this.state.meas_workload) measures.push('workload');
        if (this.state.meas_tasks) measures.push('tasks');
        if (this.state.meas_prod) measures.push('prod');
        if (this.state.meas_att) measures.push('att');
        if (this.state.meas_turnover) measures.push('turnover');
        if (this.state.meas_sales) measures.push('sales');
        if (this.state.meas_leaves) measures.push('leaves');
        if (this.state.meas_absence) measures.push('absence');

        if (measures.length === 0) {
            alert("Please select at least one KPI to export.");
            return;
        }
        this.state.showExportModal = false;

        const kwargs = {
            period: this.state.period,
            start_date: this.state.start_date,
            end_date: this.state.end_date,
            filters: this.state.filters,
            search_query: this.state.search_query,
            active_filters: this.state.active_filters,
            export_group: this.state.export_group,
            export_measures: measures,
            detailed_excel: this.state.detailed_excel
        };
        const attachmentId = await this.orm.call("wb.hr.dashboard", "export_custom_pivot_excel", [kwargs]);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    async downloadPdf() {
        this.state.showPdfModal = false;
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
        doc.text(`From Date: ${this.state.start_date || ''}      To Date: ${this.state.end_date || ''}`, 14, currentY);
        currentY += 7;
        if (this.state.search_query) {
            doc.text(`Employee Name: ${this.state.search_query}`, 14, currentY);
            currentY += 7;
        }

        const kpiBody = [];
        if (this.state.pdf_emp) {
            kpiBody.push(["Total Employees", this.state.employee_count]);
            kpiBody.push(["Employee Turnover", this.state.emp_turnover + "%"]);
        }
        if (this.state.pdf_workload) {
            kpiBody.push(["Total Workload", this.state.workload_hours + " Hrs"]);
            kpiBody.push(["Completed Tasks", this.state.tasks_complete]);
            kpiBody.push(["Productivity", this.state.production_kpi + "%"]);
        }
        if (this.state.pdf_att) {
            kpiBody.push(["Employee Attendances", this.state.attendance + "%"]);
            kpiBody.push(["Employee Vocations", this.state.average_leaves + "%"]);
            kpiBody.push(["Employee absenteeism", this.state.absence + "%"]);
        }
        if (this.state.pdf_sales) {
            kpiBody.push(["Sales Done/Employee", this.state.sales_per_emp]);
        }

        doc.autoTable({
            startY: currentY + 3,
            head: [['Key Performance Indicator', 'Value']],
            body: kpiBody.length > 0 ? kpiBody : [["No KPIs selected", "-"]],
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
        const self = this;

        const ctx = document.querySelector('.my_dashboard_chart');
        if (ctx && this.chartData) {
            if (ctx.chartInstance) ctx.chartInstance.destroy();
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

        const scatterCtx = document.querySelector('.scatter_analytics_chart');
        if (scatterCtx && this.scatterData) {
            if (scatterCtx.chartInstance) scatterCtx.chartInstance.destroy();
            scatterCtx.chartInstance = new window.Chart(scatterCtx, {
                type: 'scatter',
                data: {
                    datasets: [{
                        label: 'Employees',
                        data: this.scatterData,
                        backgroundColor: '#4f46e5',
                        pointRadius: 6,
                        pointHoverRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: (event, elements, chart) => {
                        if (elements && elements.length > 0) {
                            const clickedIndex = elements[0].index;
                            const dataPoint = chart.data.datasets[0].data[clickedIndex];
                            self.openEmployeeAllTasks(dataPoint.name);
                        }
                    },
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    scales: {
                        x: {
                            title: { display: true, text: 'Assigned Workload (Hours)', font: {weight: 'bold'} },
                            beginAtZero: true
                        },
                        y: {
                            title: { display: true, text: 'Tasks Completed', font: {weight: 'bold'} },
                            beginAtZero: true
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const dataPoint = context.raw;
                                    return `${dataPoint.name}: ${dataPoint.x} Hrs / ${dataPoint.y} Tasks`;
                                }
                            }
                        }
                    }
                }
            });
        }

        const combinedCtx = document.querySelector(".productivity_trend_chart");
        if (combinedCtx) {
            if (combinedCtx.chartInstance) combinedCtx.chartInstance.destroy();

            combinedCtx.chartInstance = new window.Chart(combinedCtx, {
                type: 'line',
                data: {
                    labels: this.state.prod_trend_labels || [],
                    datasets: [
                        {
                            label: 'Productivity %',
                            data: this.state.prod_trend_data || [],
                            borderColor: '#22c55e',
                            backgroundColor: 'rgba(34, 197, 94, 0.1)',
                            borderWidth: 3,
                            pointRadius: 4,
                            fill: true,
                            tension: 0.4,
                        },
                        {
                            label: 'Turnover %',
                            data: this.trendData || [],
                            borderColor: '#ef4444',
                            backgroundColor: 'transparent',
                            borderWidth: 2,
                            pointRadius: 4,
                            tension: 0.4,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false,
                    },
                    onClick: (event, elements, chart) => {
                        if (elements && elements.length > 0) {
                            const clickedIndex = elements[0].index;
                            const datasetIndex = elements[0].datasetIndex;
                            const monthLabel = chart.data.labels[clickedIndex];
                            self.openTrendDetails(monthLabel, datasetIndex);
                        }
                    },
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            min: 0,
                            max: 100,
                            ticks: {
                                callback: function(value) {
                                    return value + "%";
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { usePointStyle: true }
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return `${context.dataset.label}: ${context.parsed.y}%`;
                                }
                            }
                        }
                    }
                }
            });
        }

        const anovaCtx = document.querySelector('.anova_variance_chart');
        if (anovaCtx && this.anovaLabels && this.anovaLabels.length > 0) {
            if (anovaCtx.chartInstance) anovaCtx.chartInstance.destroy();

            anovaCtx.chartInstance = new window.Chart(anovaCtx, {
                type: 'bar',
                data: {
                    labels: this.anovaLabels,
                    datasets: [
                        {
                            type: 'bar',
                            label: 'Mean Productivity (%)',
                            data: this.anovaMeans,
                            backgroundColor: 'rgba(54, 162, 235, 0.7)',
                            borderColor: 'rgba(54, 162, 235, 1)',
                            borderWidth: 1,
                            borderRadius: 4,
                            yAxisID: 'y',
                        },
                        {
                            type: 'line',
                            label: 'Variance (Dispersion)',
                            data: this.anovaVariances,
                            backgroundColor: '#ef4444',
                            borderColor: '#ef4444',
                            borderWidth: 3,
                            pointRadius: 5,
                            pointBackgroundColor: '#fff',
                            tension: 0.3,
                            yAxisID: 'y1',
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false,
                    },
                    onClick: (event, elements, chart) => {
                        if (elements && elements.length > 0) {
                            const clickedIndex = elements[0].index;
                            const deptName = chart.data.labels[clickedIndex];
                            self.openDepartmentEmployees(deptName);
                        }
                    },
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    scales: {
                        y: {
                            type: 'linear',
                            display: true,
                            position: 'left',
                            title: { display: true, text: 'Mean Productivity (%)', font: {weight: 'bold'} },
                            min: 0,
                            max: 100,
                            ticks: { callback: function(value) { return value + "%"; } }
                        },
                        y1: {
                            type: 'linear',
                            display: true,
                            position: 'right',
                            title: { display: true, text: 'Variance (Instability)', font: {weight: 'bold'} },
                            grid: { drawOnChartArea: false },
                        }
                    },
                    plugins: {
                        legend: { position: 'top' },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    let label = context.dataset.label || '';
                                    if (label) { label += ': '; }
                                    if (context.parsed.y !== null) {
                                        label += context.dataset.type === 'bar' ? context.parsed.y + '%' : context.parsed.y;
                                    }
                                    return label;
                                }
                            }
                        }
                    }
                }
            });
        }
    }
}
HrDashboard.template = "HRdashboard";
registry.category("actions").add("hr_dashboard_client_tag", HrDashboard);