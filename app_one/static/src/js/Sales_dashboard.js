/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";

export class SalesDashboardClient extends Component {
    static template = "SalesDashboardClientTemplate";

    setup() {
        this.orm = useService("orm");

        this.customerChartRef = useRef("customer_chart");
        this.productChartRef = useRef("product_chart");
        this.trendChartRef = useRef("trend_chart");
        this.salespersonChartRef = useRef("salesperson_chart");
        this.categoryChartRef = useRef("category_chart");
        this.winRateChartRef = useRef("win_rate_chart");

        this.state = useState({
            state: "sale", user_id: "all", warehouse_id: "all",
            team_id: "all", category_id: "all", partner_id: "all",
            period: "7", date_from: "", date_to: "",
            filter_warehouses: [], filter_users: [], filter_teams: [], filter_categories: [], filter_partners: [],

            total_revenue: 0, total_orders: 0, aov: 0, sales_growth: 0,
            gross_profit: 0, profit_margin: 0, total_discount: 0, outstanding_receivables: 0,
            win_rate: 0, won_quotes: 0, lost_quotes: 0,

            customer_labels: [], customer_data: [], product_labels: [], product_data: [],
            trend_labels: [], trend_data: [], salesperson_labels: [], salesperson_data: [],
            category_labels: [], category_data: [],

            showExportModal: false,
            export_group: "partner_id",
            meas_revenue: true, meas_qty: true, meas_profit: false, meas_orders: false,
            meas_aov: false, meas_discount: false, meas_margin_pct: false,
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async loadFilters() {
        const data = await this.orm.call("wb.sales.dashboard", "get_filter_options", []);
        if (data) {
            this.state.filter_warehouses = data.warehouses;
            this.state.filter_users = data.users;
            this.state.filter_teams = data.teams;
            this.state.filter_categories = data.categories;
            this.state.filter_partners = data.partners;
        }
    }

    async applyDateFilter() { if (this.state.date_from && this.state.date_to) { this.state.period = "0"; await this.fetchData(); } }
    async onChangePeriod() { this.state.date_from = ""; this.state.date_to = ""; await this.fetchData(); }
    async onChangeFilter() { await this.fetchData(); }

    async fetchData() {
        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, warehouse_id: this.state.warehouse_id,
            team_id: this.state.team_id, category_id: this.state.category_id, partner_id: this.state.partner_id,
            period: parseInt(this.state.period) || 0,
            date_from: this.state.date_from || false, date_to: this.state.date_to || false,
        };
        const data = await this.orm.call("wb.sales.dashboard", "get_sales_dashboard_data", [], kwargs);
        if (data) { Object.assign(this.state, data); this.renderCharts(); }
    }

    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }

    async downloadCustomExcel() {
        this.state.showExportModal = false;
        const measures = [];
        if (this.state.meas_revenue) measures.push('revenue');
        if (this.state.meas_qty) measures.push('qty');
        if (this.state.meas_profit) measures.push('profit');
        if (this.state.meas_orders) measures.push('order_count');
        if (this.state.meas_aov) measures.push('aov');
        if (this.state.meas_discount) measures.push('discount');
        if (this.state.meas_margin_pct) measures.push('margin_pct');

        if (measures.length === 0) { alert("Please select at least one measure to export."); return; }

        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, warehouse_id: this.state.warehouse_id,
            team_id: this.state.team_id, category_id: this.state.category_id, partner_id: this.state.partner_id,
            period: parseInt(this.state.period) || 0,
            date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures,
        };
        const attachmentId = await this.orm.call("wb.sales.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    printPDF() {
        const element = document.getElementById('pdf_export_area');
        const opt = {
            margin:       0.2,
            filename:     `Sales_Dashboard_${new Date().toISOString().split('T')[0]}.pdf`,
            image:        { type: 'jpeg', quality: 1 },
            html2canvas:  { scale: 2, useCORS: true },
            jsPDF:        { unit: 'in', format: 'a3', orientation: 'landscape' }
        };
        window.html2pdf().set(opt).from(element).save();
    }

    renderCharts() {
        this._renderSingleChart(this.trendChartRef, 'line', this.state.trend_labels, this.state.trend_data, '#4e73df', 'Sales Trend');
        this._renderSingleChart(this.customerChartRef, 'bar', this.state.customer_labels, this.state.customer_data, '#36b9cc', 'Revenue');
        this._renderDoughnut(this.productChartRef, this.state.product_labels, this.state.product_data, ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b']);

        this._renderDoughnut(this.winRateChartRef, ['Won Orders', 'Lost/Draft'], [this.state.won_quotes, this.state.lost_quotes], ['#22c55e', '#cbd5e1']);

        if (this.state.user_id === "all") {
            this._renderHorizontalBar(this.salespersonChartRef, this.state.salesperson_labels, this.state.salesperson_data);
            this._renderPie(this.categoryChartRef, this.state.category_labels, this.state.category_data);
        } else {
            this._renderPie(this.categoryChartRef, this.state.category_labels, this.state.category_data);
        }
    }

    _renderSingleChart(ref, type, labels, data, color, label) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: type, data: { labels: labels, datasets: [{ label: label, data: data, backgroundColor: color, borderColor: color, fill: type === 'line', tension: 0.4 }] },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }

    _renderDoughnut(ref, labels, data, colors) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: colors }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
        });
    }

    _renderHorizontalBar(ref, labels, data) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'bar', data: { labels: labels, datasets: [{ label: 'Revenue', data: data, backgroundColor: '#f6c23e' }] },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false }
        });
    }

    _renderPie(ref, labels, data) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'pie', data: { labels: labels, datasets: [{ data: data, backgroundColor: ['#e74a3b', '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e'] }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } }
        });
    }
}
registry.category("actions").add("sales_dashboard_client_tag", SalesDashboardClient);