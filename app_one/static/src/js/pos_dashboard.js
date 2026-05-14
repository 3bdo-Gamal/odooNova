/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";

export class PosDashboardClient extends Component {
    static template = "PosDashboardClientTemplate";

    get currentField() {
        if (!this.state.model_fields || this.state.model_fields.length === 0) return {};
        return this.state.model_fields.find(f => f.name === this.state.cf_field) || {};
    }

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.hourlyChartRef = useRef("hourly_chart");
        this.productChartRef = useRef("product_chart");
        this.dynamicChartRef = useRef("dynamic_chart");

        const savedState = JSON.parse(localStorage.getItem('wb_pos_dashboard_state')) || {};
        const savedFavorites = JSON.parse(localStorage.getItem('pos_dashboard_favorites')) || [];
        const defaultFav = savedFavorites.find(f => f.is_default === true);

        this.state = useState({
            showSidebar: true,
            top_products: String(savedState.top_products || "5"),
            state: String(savedState.state || "all"), user_id: String(savedState.user_id || "all"),
            config_id: String(savedState.config_id || "all"), category_id: String(savedState.category_id || "all"),
            payment_method_id: String(savedState.payment_method_id || "all"),
            period: String(savedState.period || "7"), date_from: savedState.date_from || "", date_to: savedState.date_to || "",

            filter_configs: [], filter_users: [], filter_categories: [], filter_payment_methods: [], model_fields: [],
            pos_revenue: 0, pos_orders_count: 0, aov: 0, cash_ratio: 0, card_ratio: 0, discount_pct: 0, refund_rate: 0,
            nav_domain: [],

            hourly_labels: [], hourly_data: [], product_labels: [], product_data: [],
            dynamic_chart_labels: [], dynamic_chart_data: [],

            // Custom Search & Filter States
            search_query: defaultFav ? defaultFav.search_query : (savedState.search_query || ''),
            active_filters: defaultFav ? { ...defaultFav.active_filters } : (savedState.active_filters || { my_orders: false }),
            custom_domain: defaultFav ? [...defaultFav.custom_domain] : (savedState.custom_domain || []),
            group_by_list: defaultFav ? [...defaultFav.group_by_list] : (savedState.group_by_list || []),

            show_custom_filter_menu: false, cf_field: '', cf_operator: '=', cf_value: '',
            show_custom_group_menu: false, cg_field: '',

            active_favorite_name: defaultFav ? defaultFav.name : null, saved_favorites: savedFavorites,
            show_save_menu: false, favorite_name: 'POS Analytics', is_default_fav: false,

            showExportModal: false, showPdfModal: false, export_group: "config_id", detailed_excel: false,
            meas_revenue: true, meas_qty: true, meas_discount: false,
            pdf_revenue: true, pdf_orders: true, pdf_ratios: true
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });

        onWillUnmount(() => {
            if (this.hourlyChartRef.el && this.hourlyChartRef.el.chartInstance) this.hourlyChartRef.el.chartInstance.destroy();
            if (this.productChartRef.el && this.productChartRef.el.chartInstance) this.productChartRef.el.chartInstance.destroy();
            if (this.dynamicChartRef.el && this.dynamicChartRef.el.chartInstance) this.dynamicChartRef.el.chartInstance.destroy();
        });
    }

    async loadFilters() {
        const data = await this.orm.call("wb.pos.dashboard", "get_filter_options", []);
        if (data) {
            this.state.filter_configs = data.pos_configs || []; this.state.filter_users = data.users || [];
            this.state.filter_categories = data.categories || []; this.state.filter_payment_methods = data.payment_methods || [];
            this.state.model_fields = data.model_fields || [];
            if(this.state.model_fields.length > 0) {
                this.state.cf_field = this.state.model_fields[0].name;
                this.state.cg_field = this.state.model_fields[0].name;
            }
        }
    }

    // Filter Handlers
    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }
    async applyDateFilter() { if (this.state.date_from && this.state.date_to) { this.state.period = "0"; await this.fetchData(); } }
    async onChangePeriod() { this.state.date_from = ""; this.state.date_to = ""; await this.fetchData(); }
    async onChangeFilter() { await this.fetchData(); }

    async onSearchKeyUp(ev) {
        if (ev.key === 'Enter' && ev.target.value.trim() !== '') {
            this.state.active_favorite_name = null; this.state.search_query = ev.target.value;
            ev.target.value = ''; await this.fetchData();
        }
    }
    async clearSearchQuery() { this.state.active_favorite_name = null; this.state.search_query = ''; await this.fetchData(); }

    async toggleFilter(filterName) {
        this.state.active_favorite_name = null;
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
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
            this.state.active_favorite_name = null; this.state.cf_value = ''; this.state.show_custom_filter_menu = false;
            await this.fetchData();
        }
    }
    async removeCustomFilter(index) { this.state.custom_domain.splice(index, 1); await this.fetchData(); }

    toggleCustomGroupMenu(ev) { ev.stopPropagation(); this.state.show_custom_group_menu = !this.state.show_custom_group_menu; }
    async addCustomGroupBy(ev) {
        ev.stopPropagation();
        if(this.state.cg_field && !this.state.group_by_list.includes(this.state.cg_field)) {
            this.state.group_by_list.push(this.state.cg_field); this.state.show_custom_group_menu = false;
            await this.fetchData();
        }
    }
    async toggleGroupBy(groupName) {
        if (this.state.group_by_list.includes(groupName)) this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        else this.state.group_by_list.push(groupName);
        await this.fetchData();
    }
    async removeGroupBy(groupName) { this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName); await this.fetchData(); }

    toggleSaveMenu(ev) { ev.stopPropagation(); this.state.show_save_menu = !this.state.show_save_menu; }
    saveFavoriteUI(ev) {
        ev.stopPropagation();
        if (this.state.favorite_name.trim()) {
            if (this.state.is_default_fav) this.state.saved_favorites.forEach(f => f.is_default = false);
            const newFav = {
                id: Date.now(), name: this.state.favorite_name, search_query: this.state.search_query,
                active_filters: { ...this.state.active_filters }, custom_domain: [...this.state.custom_domain],
                group_by_list: [...this.state.group_by_list], is_default: this.state.is_default_fav
            };
            this.state.saved_favorites.push(newFav);
            localStorage.setItem('pos_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
            this.state.show_save_menu = false; this.state.favorite_name = 'POS Analytics'; this.state.is_default_fav = false;
        }
    }
    loadFavorite(fav) {
        this.state.search_query = fav.search_query; this.state.active_filters = { ...fav.active_filters };
        this.state.custom_domain = [...fav.custom_domain]; this.state.group_by_list = [...fav.group_by_list];
        this.state.active_favorite_name = fav.name; this.fetchData();
    }
    async clearFavorite() {
        this.state.active_favorite_name = null; this.state.search_query = ''; this.state.active_filters = { my_orders: false };
        this.state.custom_domain = []; this.state.group_by_list = []; await this.fetchData();
    }
    deleteFavorite(favId) {
        this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== favId);
        localStorage.setItem('pos_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
    }

    async fetchData() {
        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, config_id: this.state.config_id,
            category_id: this.state.category_id, payment_method_id: this.state.payment_method_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            top_products: this.state.top_products, search_query: this.state.search_query,
            active_filters: this.state.active_filters, custom_domain: this.state.custom_domain, group_by_list: this.state.group_by_list
        };
        const data = await this.orm.call("wb.pos.dashboard", "get_pos_dashboard_data", [], kwargs);
        if (data) {
            Object.assign(this.state, data);
            this.state.aov = this.state.pos_orders_count > 0 ? (this.state.pos_revenue / this.state.pos_orders_count).toFixed(2) : 0;
            this.renderCharts();

            localStorage.setItem('wb_pos_dashboard_state', JSON.stringify({
                top_products: String(this.state.top_products), state: String(this.state.state),
                user_id: String(this.state.user_id), config_id: String(this.state.config_id),
                category_id: String(this.state.category_id), payment_method_id: String(this.state.payment_method_id),
                period: String(this.state.period), date_from: this.state.date_from, date_to: this.state.date_to,
                search_query: this.state.search_query, active_filters: this.state.active_filters,
                custom_domain: this.state.custom_domain, group_by_list: this.state.group_by_list
            }));
        }
    }

    openRecords(type) {
        let domain = [...this.state.nav_domain];
        if (type === 'refunds') domain.push(['amount_total', '<', 0]);
        this.action.doAction({ name: "POS Orders", type: "ir.actions.act_window", res_model: "pos.order", view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: domain });
    }

    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    openPdfModal() { this.state.showPdfModal = true; }
    closePdfModal() { this.state.showPdfModal = false; }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const element = document.getElementById('print_report_area'); element.style.display = 'block';
        const opt = { margin: 0.5, filename: `POS_KPI_Report_${new Date().toISOString().split('T')[0]}.pdf`, image: { type: 'jpeg', quality: 0.98 }, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' } };
        window.html2pdf().set(opt).from(element).save().then(() => { element.style.display = 'none'; });
    }

    async downloadCustomExcel() {
        this.state.showExportModal = false;
        const measures = [];
        if (this.state.meas_revenue) measures.push('revenue');
        if (this.state.meas_qty) measures.push('qty');
        if (this.state.meas_discount) measures.push('discount');
        if (measures.length === 0) { alert("Please select at least one measure."); return; }

        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, config_id: this.state.config_id, payment_method_id: this.state.payment_method_id,
            category_id: this.state.category_id, company_id: this.state.company_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures, detailed_excel: this.state.detailed_excel,
            search_query: this.state.search_query, active_filters: this.state.active_filters, custom_domain: this.state.custom_domain
        };
        const attachmentId = await this.orm.call("wb.pos.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    renderCharts() {
        this._renderChart(this.hourlyChartRef, 'bar', this.state.hourly_labels, this.state.hourly_data, '#3b82f6', 'Revenue per Hour');
        this._renderDoughnut(this.productChartRef, this.state.product_labels, this.state.product_data, ['#4f46e5', '#10b981', '#06b6d4', '#f59e0b', '#ef4444']);

        if (this.state.group_by_list && this.state.group_by_list.length > 0) {
            this._renderChart(this.dynamicChartRef, 'bar', this.state.dynamic_chart_labels, this.state.dynamic_chart_data, '#8b5cf6', 'Grouped Revenue');
        } else if (this.dynamicChartRef.el && this.dynamicChartRef.el.chartInstance) {
            this.dynamicChartRef.el.chartInstance.destroy();
        }
    }

    _renderChart(ref, type, labels, data, color, label) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: type, data: { labels: labels, datasets: [{ label: label, data: data, backgroundColor: color, borderColor: color, fill: type === 'line', tension: 0.4, borderRadius: type === 'bar' ? 4 : 0 }] }, options: { responsive: true, maintainAspectRatio: false } });
    }

    _renderDoughnut(ref, labels, data, colors) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, hoverOffset: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } } });
    }
}
registry.category("actions").add("pos_dashboard_client_tag", PosDashboardClient);