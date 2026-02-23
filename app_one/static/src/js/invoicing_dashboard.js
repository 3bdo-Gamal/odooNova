/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";

export class InvoicingDashboardClient extends Component {
    static template = "InvoicingDashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.ratioChartRef = useRef("ratio_chart");
        this.trendChartRef = useRef("trend_chart");

        this.state = useState({
            period: 30,
            total_invoiced: 0, paid_ratio: 0, unpaid_ratio: 0,
            overdue_amount: 0, cash_collected: 0, dso: 0,
            trend_labels: [], trend_data: [],
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async fetchData() {
        const data = await this.orm.call("wb.invoicing.dashboard", "get_invoicing_data", [this.state.period]);
        if (data) {
            Object.assign(this.state, data);
            this.renderCharts();
        }
    }

    renderCharts() {
        // 1. Doughnut Chart (Status)
        if (this.ratioChartRef.el) {
            if (this.ratioChartRef.el.chartInstance) this.ratioChartRef.el.chartInstance.destroy();
            this.ratioChartRef.el.chartInstance = new window.Chart(this.ratioChartRef.el, {
                type: 'doughnut',
                data: { labels: ['Paid %', 'Unpaid %'], datasets: [{ data: [this.state.paid_ratio, this.state.unpaid_ratio], backgroundColor: ['#1cc88a', '#f6c23e'] }] },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
        // 2. Line Chart (Trend)
        if (this.trendChartRef.el) {
            if (this.trendChartRef.el.chartInstance) this.trendChartRef.el.chartInstance.destroy();
            this.trendChartRef.el.chartInstance = new window.Chart(this.trendChartRef.el, {
                type: 'line',
                data: { labels: this.state.trend_labels, datasets: [{ label: 'Collected Amount', data: this.state.trend_data, borderColor: '#4e73df', backgroundColor: 'rgba(78, 115, 223, 0.1)', fill: true, tension: 0.3 }] },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
    }

    async onChangePeriod(ev) {
        this.state.period = parseInt(ev.target.value);
        await this.fetchData();
    }
}
registry.category("actions").add("invoicing_dashboard_client_tag", InvoicingDashboardClient);