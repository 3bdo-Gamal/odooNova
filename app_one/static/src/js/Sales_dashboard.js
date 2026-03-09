/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef, useSubEnv } from "@odoo/owl";
import { SearchModel } from "@web/search/search_model";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class SalesDashboardClient extends Component {
    static template = "SalesDashboardClientTemplate";
    static components = { SearchBar };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.viewService = useService("view");

        this.customerChartRef = useRef("customer_chart");
        this.productChartRef = useRef("product_chart");
        this.trendChartRef = useRef("trend_chart");
        this.salespersonChartRef = useRef("salesperson_chart");
        this.categoryChartRef = useRef("category_chart");
        this.winRateChartRef = useRef("win_rate_chart");

        this.state = useState({
            showSidebar: true,
            top_products: "5", top_customers: "5",
            state: "sale", user_id: "all", warehouse_id: "all", team_id: "all", category_id: "all", country_id: "all", company_id: "all",
            period: "7", date_from: "", date_to: "",
            filter_warehouses: [], filter_users: [], filter_teams: [], filter_categories: [], filter_countries: [], filter_companies: [],

            total_revenue: 0, total_orders: 0, aov: 0, sales_growth: 0, total_invoiced: 0,
            gross_profit: 0, profit_margin: 0, total_discount: 0, outstanding_receivables: 0,
            win_rate: 0, won_quotes: 0, lost_quotes: 0,
            nav_domain: [], unpaid_domain: [], invoiced_domain: [],

            customer_labels: [], customer_data: [], product_labels: [], product_data: [],
            trend_labels: [], trend_data: [], salesperson_labels: [], salesperson_data: [],
            category_labels: [], category_data: [],

            showExportModal: false, showPdfModal: false, export_group: "partner_id", detailed_excel: false,
            meas_revenue: true, meas_qty: true, meas_profit: false, meas_orders: false, meas_aov: false, meas_discount: false, meas_margin_pct: false,
            pdf_revenue: true, pdf_orders: true, pdf_growth: true, pdf_profit: true, pdf_outstanding: true
        });

        this.searchModel = new SearchModel(this.env, { user: useService("user"), orm: this.orm, view: this.viewService });
        useSubEnv({ searchModel: this.searchModel });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();

            try {
                const views = await this.orm.call("sale.order", "get_views", [], { views: [[false, "search"]], options: { toolbar: false, action_id: false } });
                await this.searchModel.load({ resModel: "sale.order", context: {}, searchViewId: views.views.search.id, searchViewArch: views.views.search.arch, searchViewFields: views.models["sale.order"] });
                this.searchModel.addEventListener("update", () => { this.fetchData(); });
            } catch (error) { console.error("Failed to load search model:", error); }
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async loadFilters() {
        try {
            const data = await this.orm.call("wb.sales.dashboard", "get_filter_options", []);
            if (data) {
                this.state.filter_warehouses = data.warehouses || []; this.state.filter_users = data.users || [];
                this.state.filter_teams = data.teams || []; this.state.filter_categories = data.categories || [];
                this.state.filter_countries = data.countries || []; this.state.filter_companies = data.companies || [];
            }
        } catch (error) { console.error("Error loading filters:", error); }
    }

    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }
    async applyDateFilter() { if (this.state.date_from && this.state.date_to) { this.state.period = "0"; await this.fetchData(); } }
    async onChangePeriod() { this.state.date_from = ""; this.state.date_to = ""; await this.fetchData(); }
    async onChangeFilter() { await this.fetchData(); }

    async fetchData() {
        const searchDomain = this.env.searchModel ? this.env.searchModel.domain : [];
        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, warehouse_id: this.state.warehouse_id,
            team_id: this.state.team_id, category_id: this.state.category_id, country_id: this.state.country_id, company_id: this.state.company_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            top_products: this.state.top_products, top_customers: this.state.top_customers, native_domain: searchDomain
        };
        const data = await this.orm.call("wb.sales.dashboard", "get_sales_dashboard_data", [], kwargs);
        if (data) { Object.assign(this.state, data); this.renderCharts(); }
    }

    // Logic for Drilling Down from KPI Cards
    openRecords(type) {
        let domain = []; let model = 'sale.order'; let name = "Sales Orders";
        if (type === 'orders' || type === 'revenue') {
            domain = [...this.state.nav_domain];
            if(this.state.state === 'quotation') domain.push(['state', 'in', ['draft', 'sent']]);
            else if(this.state.state === 'sale') domain.push(['state', 'in', ['sale', 'done']]);
            else domain.push(['state', '!=', 'cancel']);
        } else if (type === 'outstanding') {
            domain = this.state.unpaid_domain; model = 'account.move'; name = "Outstanding Invoices";
        } else if (type === 'invoiced') {
            domain = this.state.invoiced_domain; model = 'account.move'; name = "Invoiced Records";
        }
        this.action.doAction({ name: name, type: "ir.actions.act_window", res_model: model, view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: domain });
    }

    // Logic for Drilling Down from Charts
    openChartRecords(type, label) {
        if (!label || label === 'Unknown' || label === 'Uncategorized') return;
        let domain = [...this.state.nav_domain];
        if(this.state.state === 'quotation') domain.push(['state', 'in', ['draft', 'sent']]);
        else if(this.state.state === 'sale') domain.push(['state', 'in', ['sale', 'done']]);
        else domain.push(['state', '!=', 'cancel']);

        if (type === 'customer') domain.push(['partner_id.name', '=', label]);
        else if (type === 'product') domain.push(['order_line.product_id.name', '=', label]);
        else if (type === 'salesperson') domain.push(['user_id.name', '=', label]);
        else if (type === 'category') domain.push(['order_line.product_id.categ_id.name', '=', label]);
        else if (type === 'trend') {
            domain.push(['date_order', '>=', `${label} 00:00:00`]);
            domain.push(['date_order', '<=', `${label} 23:59:59`]);
        } else if (type === 'win_rate') {
            domain = [...this.state.nav_domain];
            if (label === 'Won Orders') domain.push(['state', 'in', ['sale', 'done']]);
            else domain.push(['state', 'in', ['draft', 'sent', 'cancel']]);
        }

        this.action.doAction({ name: `Records for ${label}`, type: "ir.actions.act_window", res_model: "sale.order", view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: domain });
    }

    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    openPdfModal() { this.state.showPdfModal = true; }
    closePdfModal() { this.state.showPdfModal = false; }

    async downloadCustomExcel() {
        this.state.showExportModal = false;
        const measures = [];
        if (this.state.meas_revenue) measures.push('revenue'); if (this.state.meas_qty) measures.push('qty');
        if (this.state.meas_profit) measures.push('profit'); if (this.state.meas_orders) measures.push('order_count');
        if (this.state.meas_aov) measures.push('aov'); if (this.state.meas_discount) measures.push('discount');
        if (this.state.meas_margin_pct) measures.push('margin_pct');
        if (measures.length === 0) { alert("Please select at least one measure."); return; }

        const searchDomain = this.env.searchModel ? this.env.searchModel.domain : [];
        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, warehouse_id: this.state.warehouse_id,
            team_id: this.state.team_id, category_id: this.state.category_id, country_id: this.state.country_id, company_id: this.state.company_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures, detailed_excel: this.state.detailed_excel, native_domain: searchDomain
        };
        const attachmentId = await this.orm.call("wb.sales.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const element = document.getElementById('print_report_area'); element.style.display = 'block';
        const opt = { margin: 0.5, filename: `Sales_KPI_Report_${new Date().toISOString().split('T')[0]}.pdf`, image: { type: 'jpeg', quality: 0.98 }, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' } };
        window.html2pdf().set(opt).from(element).save().then(() => { element.style.display = 'none'; });
    }

    renderCharts() {
        this._renderChart(this.trendChartRef, 'line', this.state.trend_labels, this.state.trend_data, '#4f46e5', 'Sales Trend', 'trend');
        this._renderChart(this.customerChartRef, 'bar', this.state.customer_labels, this.state.customer_data, '#06b6d4', 'Revenue', 'customer');
        this._renderDoughnut(this.productChartRef, this.state.product_labels, this.state.product_data, ['#4f46e5', '#10b981', '#06b6d4', '#f59e0b', '#ef4444'], 'product');
        this._renderDoughnut(this.winRateChartRef, ['Won Orders', 'Lost/Draft'], [this.state.won_quotes, this.state.lost_quotes], ['#10b981', '#cbd5e1'], 'win_rate');
        this._renderHorizontalBar(this.salespersonChartRef, this.state.salesperson_labels, this.state.salesperson_data, 'salesperson');
        this._renderPie(this.categoryChartRef, this.state.category_labels, this.state.category_data, 'category');
    }

    _renderChart(ref, type, labels, data, color, label, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: type, data: { labels: labels, datasets: [{ label: label, data: data, backgroundColor: color, borderColor: color, fill: type === 'line', tension: 0.4, borderRadius: type === 'bar' ? 4 : 0 }] },
            options: { responsive: true, maintainAspectRatio: false, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } }
        });
    }

    _renderDoughnut(ref, labels, data, colors, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, hoverOffset: 4 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } }
        });
    }

    _renderHorizontalBar(ref, labels, data, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'bar', data: { labels: labels, datasets: [{ label: 'Revenue', data: data, backgroundColor: '#f59e0b', borderRadius: 4 }] },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } }
        });
    }

    _renderPie(ref, labels, data, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'pie', data: { labels: labels, datasets: [{ data: data, backgroundColor: ['#ef4444', '#4f46e5', '#10b981', '#06b6d4', '#f59e0b'], borderWidth: 2, hoverOffset: 4 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } }, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } }
        });
    }
}
registry.category("actions").add("sales_dashboard_client_tag", SalesDashboardClient);