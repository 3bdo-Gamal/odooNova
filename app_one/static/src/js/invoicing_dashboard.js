/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";

export class InvoicingDashboardClient extends Component {
    static template = "InvoicingDashboardClientTemplate";

    get currentField() {
        if (!this.state.model_fields || this.state.model_fields.length === 0) return {};
        return this.state.model_fields.find(f => f.name === this.state.cf_field) || {};
    }

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.trendChartRef = useRef("trend_chart");
        this.customerChartRef = useRef("customer_chart");
        this.statusChartRef = useRef("status_chart");
        this.dynamicChartRef = useRef("dynamic_chart");

        const savedState = JSON.parse(localStorage.getItem('wb_invoicing_dashboard_state')) || {};
        const savedFavorites = JSON.parse(localStorage.getItem('invoicing_dashboard_favorites')) || [];
        const defaultFav = savedFavorites.find(f => f.is_default === true);

        this.state = useState({
            showSidebar: true,
            period: String(savedState.period || "30"), date_from: savedState.date_from || "", date_to: savedState.date_to || "",
            journal_id: String(savedState.journal_id || "all"), user_id: String(savedState.user_id || "all"),
            company_id: String(savedState.company_id || "all"), payment_state: String(savedState.payment_state || "all"),

            filter_journals: [], filter_users: [], filter_companies: [], model_fields: [],

            total_invoiced_amount: 0, cash_collected: 0, unpaid_amount: 0,
            paid_ratio: 0, unpaid_ratio: 0, overdue_amount: 0,
            overdue_rate: 0, dso: 0, bad_debt_pct: 0, nav_domain: [],

            trend_labels: [], trend_invoiced_data: [], trend_collected_data: [],
            customer_labels: [], customer_data: [], dynamic_chart_labels: [], dynamic_chart_data: [],

            // Custom Search & Filter States
            search_query: defaultFav ? defaultFav.search_query : (savedState.search_query || ''),
            active_filters: defaultFav ? { ...defaultFav.active_filters } : (savedState.active_filters || { my_invoices: false }),
            custom_domain: defaultFav ? [...defaultFav.custom_domain] : (savedState.custom_domain || []),
            group_by_list: defaultFav ? [...defaultFav.group_by_list] : (savedState.group_by_list || []),

            show_custom_filter_menu: false, cf_field: '', cf_operator: '=', cf_value: '',
            show_custom_group_menu: false, cg_field: '',

            active_favorite_name: defaultFav ? defaultFav.name : null, saved_favorites: savedFavorites,
            show_save_menu: false, favorite_name: 'Invoicing Analytics', is_default_fav: false,

            showExportModal: false, showPdfModal: false, export_group: "journal_id", detailed_excel: false,
            meas_invoiced: true, meas_collected: true, meas_unpaid: false,
            pdf_invoiced: true, pdf_unpaid: true, pdf_ratios: true
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });

        onWillUnmount(() => {
            if (this.trendChartRef.el?.chartInstance) this.trendChartRef.el.chartInstance.destroy();
            if (this.customerChartRef.el?.chartInstance) this.customerChartRef.el.chartInstance.destroy();
            if (this.statusChartRef.el?.chartInstance) this.statusChartRef.el.chartInstance.destroy();
            if (this.dynamicChartRef.el?.chartInstance) this.dynamicChartRef.el.chartInstance.destroy();
        });
    }

    async loadFilters() {
        const data = await this.orm.call("wb.invoicing.dashboard", "get_filter_options", []);
        if (data) {
            this.state.filter_journals = data.journals || []; this.state.filter_users = data.users || [];
            this.state.filter_companies = data.companies || []; this.state.model_fields = data.model_fields || [];
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
            localStorage.setItem('invoicing_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
            this.state.show_save_menu = false; this.state.favorite_name = 'Invoicing Analytics'; this.state.is_default_fav = false;
        }
    }
    loadFavorite(fav) {
        this.state.search_query = fav.search_query; this.state.active_filters = { ...fav.active_filters };
        this.state.custom_domain = [...fav.custom_domain]; this.state.group_by_list = [...fav.group_by_list];
        this.state.active_favorite_name = fav.name; this.fetchData();
    }
    async clearFavorite() {
        this.state.active_favorite_name = null; this.state.search_query = ''; this.state.active_filters = { my_invoices: false };
        this.state.custom_domain = []; this.state.group_by_list = []; await this.fetchData();
    }
    deleteFavorite(favId) {
        this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== favId);
        localStorage.setItem('invoicing_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
    }

    async fetchData() {
        const kwargs = {
            journal_id: this.state.journal_id, user_id: this.state.user_id,
            company_id: this.state.company_id, payment_state: this.state.payment_state,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            search_query: this.state.search_query, active_filters: this.state.active_filters,
            custom_domain: this.state.custom_domain, group_by_list: this.state.group_by_list
        };
        const data = await this.orm.call("wb.invoicing.dashboard", "get_invoicing_dashboard_data", [], kwargs);
        if (data) {
            Object.assign(this.state, data);
            this.renderCharts();

            localStorage.setItem('wb_invoicing_dashboard_state', JSON.stringify({
                journal_id: String(this.state.journal_id), user_id: String(this.state.user_id),
                company_id: String(this.state.company_id), payment_state: String(this.state.payment_state),
                period: String(this.state.period), date_from: this.state.date_from, date_to: this.state.date_to,
                search_query: this.state.search_query, active_filters: this.state.active_filters,
                custom_domain: this.state.custom_domain, group_by_list: this.state.group_by_list
            }));
        }
    }

    openRecords(type) {
        let domain = [...this.state.nav_domain];
        if (type === 'unpaid') domain.push(['payment_state', 'in', ['not_paid', 'partial']]);
        if (type === 'overdue') {
            domain.push(['payment_state', 'in', ['not_paid', 'partial']]);
            domain.push(['invoice_date_due', '<', new Date().toISOString().split('T')[0]]);
        }
        this.action.doAction({ name: "Invoices", type: "ir.actions.act_window", res_model: "account.move", view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: domain });
    }

    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    openPdfModal() { this.state.showPdfModal = true; }
    closePdfModal() { this.state.showPdfModal = false; }

    async downloadCustomExcel() {
        this.state.showExportModal = false;
        const measures = [];
        if (this.state.meas_invoiced) measures.push('invoiced');
        if (this.state.meas_collected) measures.push('collected');
        if (this.state.meas_unpaid) measures.push('unpaid');
        if (measures.length === 0) { alert("Please select at least one measure."); return; }

        const kwargs = {
            journal_id: this.state.journal_id, user_id: this.state.user_id,
            company_id: this.state.company_id, payment_state: this.state.payment_state,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures, detailed_excel: this.state.detailed_excel,
            search_query: this.state.search_query, active_filters: this.state.active_filters, custom_domain: this.state.custom_domain
        };
        const attachmentId = await this.orm.call("wb.invoicing.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const element = document.getElementById('print_report_area'); element.style.display = 'block';
        const opt = { margin: 0.5, filename: `Invoicing_KPI_Report_${new Date().toISOString().split('T')[0]}.pdf`, image: { type: 'jpeg', quality: 0.98 }, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' } };
        window.html2pdf().set(opt).from(element).save().then(() => { element.style.display = 'none'; });
    }

    renderCharts() {
        this._renderChart(this.trendChartRef, 'line', this.state.trend_labels, [
            { label: 'Total Invoiced', data: this.state.trend_invoiced_data, borderColor: '#3b82f6', backgroundColor: '#3b82f6', tension: 0.4 },
            { label: 'Cash Collected', data: this.state.trend_collected_data, borderColor: '#10b981', backgroundColor: '#10b981', tension: 0.4 }
        ], null, null, true);

        this._renderChart(this.customerChartRef, 'bar', this.state.customer_labels, [
            { label: 'Unpaid Amount (Debt)', data: this.state.customer_data, backgroundColor: '#4f46e5', borderRadius: 4 }
        ], null, null, false, 'y');

        this._renderDoughnut(this.statusChartRef, ['Paid', 'Unpaid'], [this.state.cash_collected, this.state.unpaid_amount], ['#10b981', '#f59e0b']);

        if (this.state.group_by_list && this.state.group_by_list.length > 0) {
            this._renderChart(this.dynamicChartRef, 'bar', this.state.dynamic_chart_labels, [
                { label: 'Grouped Invoiced Amount', data: this.state.dynamic_chart_data, backgroundColor: '#8b5cf6', borderRadius: 4 }
            ]);
        } else if (this.dynamicChartRef.el?.chartInstance) {
            this.dynamicChartRef.el.chartInstance.destroy();
        }
    }

    _renderChart(ref, type, labels, datasets, color, label, isMultiple = false, indexAxis = 'x') {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        const ds = isMultiple ? datasets : [{ label: datasets[0].label, data: datasets[0].data, backgroundColor: datasets[0].backgroundColor, borderColor: datasets[0].backgroundColor, fill: type === 'line', tension: 0.4, borderRadius: datasets[0].borderRadius || 0 }];
        ref.el.chartInstance = new window.Chart(ref.el, { type: type, data: { labels: labels, datasets: ds }, options: { indexAxis: indexAxis, responsive: true, maintainAspectRatio: false } });
    }

    _renderDoughnut(ref, labels, data, colors) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, hoverOffset: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } } });
    }
}
registry.category("actions").add("invoicing_dashboard_client_tag", InvoicingDashboardClient);