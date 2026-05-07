/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";

export class SalesDashboardClient extends Component {
    static template = "SalesDashboardClientTemplate";

    get currentField() {
        if (!this.state.model_fields || this.state.model_fields.length === 0) return {};
        return this.state.model_fields.find(f => f.name === this.state.cf_field) || {};
    }

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.customerChartRef = useRef("customer_chart");
        this.productChartRef = useRef("product_chart");
        this.trendChartRef = useRef("trend_chart");
        this.salespersonChartRef = useRef("salesperson_chart");
        this.categoryChartRef = useRef("category_chart");
        this.teamChartRef = useRef("team_chart"); // New Chart Ref
        this.dynamicChartRef = useRef("dynamic_chart");

        const savedState = JSON.parse(localStorage.getItem('wb_sales_dashboard_state_v2')) || {};
        const savedFavorites = JSON.parse(localStorage.getItem('sales_dashboard_favorites')) || [];
        const defaultFav = savedFavorites.find(f => f.is_default === true);

        this.state = useState({
            showSidebar: true,
            top_products: String(savedState.top_products || "5"),
            top_customers: String(savedState.top_customers || "5"),
            top_salespeople: String(savedState.top_salespeople || "5"),
            top_categories: String(savedState.top_categories || "5"),

            state: String(savedState.state || "all"),
            user_id: String(savedState.user_id || "all"),
            warehouse_id: String(savedState.warehouse_id || "all"),
            team_id: String(savedState.team_id || "all"),
            category_id: String(savedState.category_id || "all"),
            country_id: String(savedState.country_id || "all"),
            company_id: String(savedState.company_id || "all"),
            period: String(savedState.period || "7"),
            date_from: savedState.date_from || "",
            date_to: savedState.date_to || "",

            filter_warehouses: [], filter_users: [], filter_teams: [], filter_categories: [], filter_countries: [], filter_companies: [],
            model_fields: [],

            total_revenue: 0, total_orders: 0, aov: 0, sales_growth: 0, total_invoiced: 0,
            gross_profit: 0, profit_margin: 0, total_discount: 0, outstanding_receivables: 0,
            nav_domain: [], unpaid_domain: [], invoiced_domain: [],

            customer_labels: [], customer_data: [], product_labels: [], product_data: [],
            trend_labels: [], trend_data: [], salesperson_labels: [], salesperson_data: [],
            category_labels: [], category_data: [], team_labels: [], team_data: [], dynamic_chart_labels: [], dynamic_chart_data: [],

            search_query: defaultFav ? defaultFav.search_query : (savedState.search_query || ''),
            active_filters: defaultFav ? { ...defaultFav.active_filters } : (savedState.active_filters || { my_orders: false, quotations: false, sales_orders: false, to_invoice: false }),

            custom_domain: defaultFav ? [...defaultFav.custom_domain] : (savedState.custom_domain || []),
            show_custom_filter_menu: false,
            cf_field: '', cf_operator: '=', cf_value: '',

            group_by_list: defaultFav ? [...defaultFav.group_by_list] : (savedState.group_by_list || []),
            show_custom_group_menu: false,
            cg_field: '',

            active_favorite_name: defaultFav ? defaultFav.name : null,
            saved_favorites: savedFavorites,
            show_save_menu: false,
            favorite_name: 'Sales Analytics',
            is_default_fav: false,
            is_shared_fav: false,

            showExportModal: false, showPdfModal: false, export_group: "partner_id", detailed_excel: false,
            meas_revenue: true, meas_qty: true, meas_profit: false, meas_orders: false, meas_aov: false, meas_discount: false, meas_margin_pct: false,
            pdf_revenue: true, pdf_orders: true, pdf_growth: true, pdf_profit: true, pdf_outstanding: true
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });

        onWillUnmount(() => {
            if (this.customerChartRef.el && this.customerChartRef.el.chartInstance) this.customerChartRef.el.chartInstance.destroy();
            if (this.productChartRef.el && this.productChartRef.el.chartInstance) this.productChartRef.el.chartInstance.destroy();
            if (this.trendChartRef.el && this.trendChartRef.el.chartInstance) this.trendChartRef.el.chartInstance.destroy();
            if (this.salespersonChartRef.el && this.salespersonChartRef.el.chartInstance) this.salespersonChartRef.el.chartInstance.destroy();
            if (this.categoryChartRef.el && this.categoryChartRef.el.chartInstance) this.categoryChartRef.el.chartInstance.destroy();
            if (this.teamChartRef.el && this.teamChartRef.el.chartInstance) this.teamChartRef.el.chartInstance.destroy();
            if (this.dynamicChartRef.el && this.dynamicChartRef.el.chartInstance) this.dynamicChartRef.el.chartInstance.destroy();
        });
    }

    async loadFilters() {
        try {
            const data = await this.orm.call("wb.sales.dashboard", "get_filter_options", []);
            if (data) {
                this.state.filter_warehouses = data.warehouses || []; this.state.filter_users = data.users || [];
                this.state.filter_teams = data.teams || []; this.state.filter_categories = data.categories || [];
                this.state.filter_countries = data.countries || []; this.state.filter_companies = data.companies || [];
                this.state.model_fields = data.model_fields || [];
                if(this.state.model_fields.length > 0) {
                    this.state.cf_field = this.state.model_fields[0].name;
                    this.state.cg_field = this.state.model_fields[0].name;
                }
            }
        } catch (error) { console.error("Error loading filters:", error); }
    }

    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }
    async applyDateFilter() { if (this.state.date_from && this.state.date_to) { this.state.period = "0"; await this.fetchData(); } }
    async onChangePeriod() { this.state.date_from = ""; this.state.date_to = ""; await this.fetchData(); }
    async onChangeFilter() { await this.fetchData(); }

    async onSearchKeyUp(ev) {
        if (ev.key === 'Enter' && ev.target.value.trim() !== '') {
            this.state.active_favorite_name = null;
            this.state.search_query = ev.target.value;
            ev.target.value = '';
            await this.fetchData();
        }
    }
    async clearSearchQuery() { this.state.active_favorite_name = null; this.state.search_query = ''; await this.fetchData(); }

    async toggleFilter(filterName) {
        this.state.active_favorite_name = null;
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
        if(filterName === 'quotations' && this.state.active_filters.quotations) this.state.active_filters.sales_orders = false;
        if(filterName === 'sales_orders' && this.state.active_filters.sales_orders) this.state.active_filters.quotations = false;
        await this.fetchData();
    }

    toggleCustomFilterMenu(ev) { ev.stopPropagation(); this.state.show_custom_filter_menu = !this.state.show_custom_filter_menu; }

    async addCustomFilter(ev) {
        ev.stopPropagation();
        if(this.state.cf_field && this.state.cf_value !== '') {
            const fieldObj = this.state.model_fields.find(f => f.name === this.state.cf_field);
            this.state.custom_domain.push({
                field: this.state.cf_field, label: fieldObj ? fieldObj.string : this.state.cf_field,
                operator: this.state.cf_operator, value: this.state.cf_value, type: fieldObj ? fieldObj.type : 'char'
            });
            this.state.active_favorite_name = null;
            this.state.cf_value = '';
            this.state.show_custom_filter_menu = false;
            await this.fetchData();
        }
    }

    async removeCustomFilter(index) {
        this.state.active_favorite_name = null;
        this.state.custom_domain.splice(index, 1);
        await this.fetchData();
    }

    toggleCustomGroupMenu(ev) { ev.stopPropagation(); this.state.show_custom_group_menu = !this.state.show_custom_group_menu; }

    async addCustomGroupBy(ev) {
        ev.stopPropagation();
        if(this.state.cg_field && !this.state.group_by_list.includes(this.state.cg_field)) {
            this.state.active_favorite_name = null;
            this.state.group_by_list.push(this.state.cg_field);
            this.state.show_custom_group_menu = false;
            await this.fetchData();
        }
    }

    async toggleGroupBy(groupName) {
        this.state.active_favorite_name = null;
        if (this.state.group_by_list.includes(groupName)) {
            this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        } else {
            this.state.group_by_list.push(groupName);
        }
        await this.fetchData();
    }

    async removeGroupBy(groupName) {
        this.state.active_favorite_name = null;
        this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        await this.fetchData();
    }

    toggleSaveMenu(ev) { ev.stopPropagation(); this.state.show_save_menu = !this.state.show_save_menu; }
    onDefaultCheckboxChange() { if (this.state.is_default_fav) this.state.is_shared_fav = false; }
    onSharedCheckboxChange() { if (this.state.is_shared_fav) this.state.is_default_fav = false; }

    saveFavoriteUI(ev) {
        ev.stopPropagation();
        if (this.state.favorite_name.trim()) {
            if (this.state.is_default_fav) this.state.saved_favorites.forEach(f => f.is_default = false);
            const newFav = {
                id: Date.now(), name: this.state.favorite_name, search_query: this.state.search_query,
                active_filters: { ...this.state.active_filters }, custom_domain: [...this.state.custom_domain],
                group_by_list: [...this.state.group_by_list], is_default: this.state.is_default_fav, is_shared: this.state.is_shared_fav
            };
            this.state.saved_favorites.push(newFav);
            localStorage.setItem('sales_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
            this.state.show_save_menu = false; this.state.favorite_name = 'Sales Analytics';
            this.state.is_default_fav = false; this.state.is_shared_fav = false;
        }
    }

    loadFavorite(fav) {
        this.state.search_query = fav.search_query;
        this.state.active_filters = { ...fav.active_filters };
        this.state.custom_domain = [...fav.custom_domain];
        this.state.group_by_list = [...fav.group_by_list];
        this.state.active_favorite_name = fav.name;
        this.fetchData();
    }

    async clearFavorite() {
        this.state.active_favorite_name = null;
        this.state.search_query = '';
        this.state.active_filters = { my_orders: false, quotations: false, sales_orders: false, to_invoice: false };
        this.state.custom_domain = [];
        this.state.group_by_list = [];
        await this.fetchData();
    }

    deleteFavorite(favId) {
        this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== favId);
        localStorage.setItem('sales_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
    }

    async fetchData() {
        try {
            const kwargs = {
                state: this.state.state, user_id: this.state.user_id, warehouse_id: this.state.warehouse_id, team_id: this.state.team_id,
                category_id: this.state.category_id, country_id: this.state.country_id, company_id: this.state.company_id,
                period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
                top_products: this.state.top_products, top_customers: this.state.top_customers,
                top_salespeople: this.state.top_salespeople, top_categories: this.state.top_categories,
                search_query: this.state.search_query, active_filters: this.state.active_filters,
                custom_domain: this.state.custom_domain, group_by_list: this.state.group_by_list
            };
            const data = await this.orm.call("wb.sales.dashboard", "get_sales_dashboard_data", [], kwargs);
            if (data) {
                Object.assign(this.state, data);
                this.renderCharts();

                localStorage.setItem('wb_sales_dashboard_state_v2', JSON.stringify({
                    top_products: String(this.state.top_products),
                    top_customers: String(this.state.top_customers),
                    top_salespeople: String(this.state.top_salespeople),
                    top_categories: String(this.state.top_categories),
                    state: String(this.state.state),
                    user_id: String(this.state.user_id),
                    warehouse_id: String(this.state.warehouse_id),
                    team_id: String(this.state.team_id),
                    category_id: String(this.state.category_id),
                    country_id: String(this.state.country_id),
                    company_id: String(this.state.company_id),
                    period: String(this.state.period),
                    date_from: this.state.date_from,
                    date_to: this.state.date_to,
                    search_query: this.state.search_query,
                    active_filters: this.state.active_filters,
                    custom_domain: this.state.custom_domain,
                    group_by_list: this.state.group_by_list
                }));
            }
        } catch (e) {
            console.error("Dashboard failed to fetch data:", e);
        }
    }

    openRecords(type) {
        if (type === 'orders' || type === 'revenue') {
            this.action.doAction({ name: "Sales Orders", type: "ir.actions.act_window", res_model: "sale.order", view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: this.state.nav_domain });
        } else if (type === 'to_invoice') {
            this.action.doAction({ name: "Orders To Invoice", type: "ir.actions.act_window", res_model: "sale.order", view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: this.state.to_invoice_domain });
        }else if (type === 'outstanding') {
            this.action.doAction({
                name: "Outstanding Invoices",
                type: "ir.actions.act_window",
                res_model: "account.move",
                view_mode: "list,form",
                views: [[false, "list"], [false, "form"]],
                domain: [['move_type', '=', 'out_invoice'], ['state', '=', 'posted'], ['payment_state', 'in', ['not_paid', 'partial']]]
            });
        }
    }

    openChartRecords(type, label) {
        let res_model = "sale.order";
        let views = [[false, "list"], [false, "form"]];
        let name = "All Records";
        let domain = [];

        if (type === 'product') {
            res_model = "product.template";
            views = [[false, "kanban"], [false, "list"], [false, "form"]];
            name = "All Products";
        }
        else if (type === 'customer') {
            res_model = "res.partner";
            views = [[false, "kanban"], [false, "list"], [false, "form"]];
            name = "All Customers";
        }
        else if (type === 'category') {
            res_model = "product.category";
            name = "All Product Categories";
        }
        else if (type === 'salesperson') {
            res_model = "res.users";
            name = "All Salespersons";
        }
        else if (type === 'team') {
            res_model = "crm.team";
            name = "All Sales Teams";
        }
        else if (type === 'trend') {
            name = "All Sales Orders";
        }

        this.action.doAction({
            name: name,
            type: "ir.actions.act_window",
            res_model: res_model,
            view_mode: views.map(v => v[1]).join(","),
            views: views,
            domain: domain
        });
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

        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, warehouse_id: this.state.warehouse_id, team_id: this.state.team_id,
            category_id: this.state.category_id, country_id: this.state.country_id, company_id: this.state.company_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures, detailed_excel: this.state.detailed_excel,
            search_query: this.state.search_query, active_filters: this.state.active_filters, custom_domain: this.state.custom_domain
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

        // Render New Team Chart
        this._renderDoughnut(this.teamChartRef, this.state.team_labels, this.state.team_data, ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6'], 'team');

        this._renderHorizontalBar(this.salespersonChartRef, this.state.salesperson_labels, this.state.salesperson_data, 'salesperson');
        this._renderPie(this.categoryChartRef, this.state.category_labels, this.state.category_data, 'category');

        if (this.state.group_by_list && this.state.group_by_list.length > 0) {
            this._renderChart(this.dynamicChartRef, 'bar', this.state.dynamic_chart_labels, this.state.dynamic_chart_data, '#8b5cf6', 'Grouped Revenue', 'dynamic');
        } else if (this.dynamicChartRef.el && this.dynamicChartRef.el.chartInstance) {
            this.dynamicChartRef.el.chartInstance.destroy();
        }
    }

    _renderChart(ref, type, labels, data, color, label, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: type, data: { labels: labels, datasets: [{ label: label, data: data, backgroundColor: color, borderColor: color, fill: type === 'line', tension: 0.4, borderRadius: type === 'bar' ? 4 : 0 }] }, options: { responsive: true, maintainAspectRatio: false, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } } });
    }

    _renderDoughnut(ref, labels, data, colors, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        const extendedColors = ['#4f46e5', '#10b981', '#06b6d4', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f43f5e', '#84cc16', '#0ea5e9', '#6366f1', '#d946ef', '#f97316', '#22c55e'];
        ref.el.chartInstance = new window.Chart(ref.el, { type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: extendedColors, borderWidth: 2, hoverOffset: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } }, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } } });
    }

    _renderHorizontalBar(ref, labels, data, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: 'bar', data: { labels: labels, datasets: [{ label: 'Revenue', data: data, backgroundColor: '#f59e0b', borderRadius: 4 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } } });
    }

    _renderPie(ref, labels, data, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        const extendedColors = ['#ef4444', '#4f46e5', '#10b981', '#06b6d4', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f43f5e', '#84cc16', '#0ea5e9', '#6366f1', '#d946ef', '#f97316', '#22c55e'];
        ref.el.chartInstance = new window.Chart(ref.el, { type: 'pie', data: { labels: labels, datasets: [{ data: data, backgroundColor: extendedColors, borderWidth: 2, hoverOffset: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } }, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } } });
    }
}
registry.category("actions").add("sales_dashboard_client_tag", SalesDashboardClient);