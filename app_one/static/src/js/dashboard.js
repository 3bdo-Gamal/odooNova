/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
const { Component, onWillStart, onMounted, useState } =owl;
export class HrDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({
            employee_count: 0,
            workload_hours: 0,
            tasks_complete: 0,
            production_kpi: 0,
            period:7,
        });
        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await this.downloaddata()

        });

        onMounted(() => {
            this.renderChart();
        });
    }
   async downloaddata()
            {
                try {
                    const data = await this.orm.call("wb.hr.dashboard", "compute_kpis", [this.state.period]);
                    if (data) {
                        this.state.employee_count = data.employee_count;
                        this.state.workload_hours = data.workload_hours;
                        this.state.tasks_complete = data.tasks_complete;
                        this.state.production_kpi = data.production_kpi;
                        this.state.attendance=data.attendance;
                        this.state.emp_turnover=data.emp_turnover

                        this.chartLabels = data.chart_labels;
                        this.chartData = data.chart_data;
                    }
                } catch (e) {
                    console.error("Error", e);
                }
            }
      async onChangePeriod(op){
            this.state.date=op.target.value;
             await this.downloaddata();
             await this.renderChart();
        }

    renderChart() {
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
                        backgroundColor: ['#007bff', '#ffc107', '#28a745', '#6f42c1', '#17a2b8'],
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false
                }
            });
        }
    }
}
HrDashboard.template = "HRdashboard";
registry.category("actions").add("hr_dashboard_client_tag", HrDashboard);