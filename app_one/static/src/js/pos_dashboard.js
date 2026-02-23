/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";

export class PosDashboardClient extends Component {
    static template = "PosDashboardClientTemplate";

    setup() {
        this.orm = useService("orm");
        this.hourlyChartRef = useRef("hourly_chart");
        this.paymentChartRef = useRef("payment_chart");

        this.state = useState({
            period: 7,
            pos_revenue: 0,
            pos_orders_count: 0,
            cash_ratio: 0,
            card_ratio: 0,
            pos_refund_rate: 0,
            discount_pct: 0,
            hours_labels: [],
            hours_data: [],
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await this.fetchData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async fetchData() {
        try {
            const data = await this.orm.call("wb.pos.dashboard", "get_pos_dashboard_data", [this.state.period]);
            if (data) {
                Object.assign(this.state, data);
                this.renderCharts();
            }
        } catch (e) {
            console.error("Error fetching POS dashboard data:", e);
        }
    }

    async onChangePeriod(ev) {
        this.state.period = parseInt(ev.target.value);
        await this.fetchData();
    }

    renderCharts() {
        // Line Chart: Revenue per Hour
        if (this.hourlyChartRef.el) {
            if (this.hourlyChartRef.el.chartInstance) this.hourlyChartRef.el.chartInstance.destroy();
            this.hourlyChartRef.el.chartInstance = new window.Chart(this.hourlyChartRef.el, {
                type: 'line',
                data: {
                    labels: this.state.hours_labels,
                    datasets: [{ label: 'Revenue (EGP)', data: this.state.hours_data, backgroundColor: 'rgba(28, 200, 138, 0.2)', borderColor: '#1cc88a', fill: true, tension: 0.4 }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }

        // Doughnut Chart: Cash vs Card
        if (this.paymentChartRef.el) {
            if (this.paymentChartRef.el.chartInstance) this.paymentChartRef.el.chartInstance.destroy();
            this.paymentChartRef.el.chartInstance = new window.Chart(this.paymentChartRef.el, {
                type: 'doughnut',
                data: {
                    labels: ['Cash', 'Card/Bank'],
                    datasets: [{ data: [this.state.cash_ratio, this.state.card_ratio], backgroundColor: ['#4e73df', '#858796'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });
        }
    }
}

registry.category("actions").add("pos_dashboard_client_tag", PosDashboardClient);