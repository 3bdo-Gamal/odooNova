/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";

export class SalesDashboardClient extends Component {
    // 1. Template Binding
    static template = "SalesDashboardClientTemplate";

    setup() {
        // 2. Services & References
        this.orm = useService("orm");

        this.customerChartRef = useRef("customer_chart");
        this.productChartRef = useRef("product_chart");
        this.trendChartRef = useRef("trend_chart");
        this.salespersonChartRef = useRef("salesperson_chart");
        this.categoryChartRef = useRef("category_chart");

        // 3. Reactive State
        this.state = useState({
            period: 7,
            customer_type: 'all',
            total_revenue: 0,
            total_orders: 0,
            aov: 0,
            sales_growth: 0,
            gross_profit: 0,
            profit_margin: 0,
            total_discount: 0,
            outstanding_receivables: 0,
            customer_labels: [],
            customer_data: [],
            product_labels: [],
            product_data: [],
            trend_labels: [],
            trend_data: [],
            salesperson_labels: [],
            salesperson_data: [],
            category_labels: [],
            category_data: [],
        });

        // 4. Lifecycle Hooks
        onWillStart(async () => {
            // Load Chart.js library before rendering
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await this.fetchData();
        });

        onMounted(() => {
            // Render charts after the DOM is ready
            this.renderCharts();
        });
    }

    // 5. Data Fetching
    async fetchData() {
        try {
            const data = await this.orm.call("wb.sales.dashboard", "get_sales_dashboard_data", [this.state.period, this.state.customer_type]);
            if (data) {
                Object.assign(this.state, data);
                this.renderCharts();
            }
        } catch (e) {
            console.error("Error fetching dashboard data:", e);
        }
    }

    // 6. Event Handlers
    async onChangePeriod(ev) {
        this.state.period = parseInt(ev.target.value);
        await this.fetchData();
    }

    async onChangeType(ev) {
        this.state.customer_type = ev.target.value;
        await this.fetchData();
    }

    // 7. Chart Rendering Engine
    renderCharts() {
        this._renderSingleChart(this.trendChartRef, 'line', this.state.trend_labels, this.state.trend_data, '#4e73df', 'Sales Trend');
        this._renderSingleChart(this.customerChartRef, 'bar', this.state.customer_labels, this.state.customer_data, '#36b9cc', 'Revenue');
        this._renderDoughnut(this.productChartRef, this.state.product_labels, this.state.product_data);
        this._renderHorizontalBar(this.salespersonChartRef, this.state.salesperson_labels, this.state.salesperson_data);
        this._renderPie(this.categoryChartRef, this.state.category_labels, this.state.category_data);
    }

    // 8. Chart.js Helper Methods
    _renderSingleChart(ref, type, labels, data, color, label) {
        if (!ref.el) return;
        if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: type,
            data: { labels: labels, datasets: [{ label: label, data: data, backgroundColor: color, borderColor: color, fill: type === 'line', tension: 0.4 }] },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }

    _renderDoughnut(ref, labels, data) {
        if (!ref.el) return;
        if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'doughnut',
            data: { labels: labels, datasets: [{ data: data, backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b'] }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } }
        });
    }

    _renderHorizontalBar(ref, labels, data) {
        if (!ref.el) return;
        if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'bar',
            data: { labels: labels, datasets: [{ label: 'Revenue', data: data, backgroundColor: '#f6c23e' }] },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false }
        });
    }

    _renderPie(ref, labels, data) {
        if (!ref.el) return;
        if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'pie',
            data: { labels: labels, datasets: [{ data: data, backgroundColor: ['#e74a3b', '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e'] }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } }
        });
    }
}

// 9. Action Registry
registry.category("actions").add("sales_dashboard_client_tag", SalesDashboardClient);