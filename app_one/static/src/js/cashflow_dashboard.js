/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";

export class CashFlowDashboardClient extends Component {
    static template = "CashFlowDashboardClientTemplate";

    get currentField() {
        if (!this.state.model_fields || this.state.model_fields.length === 0) return {};
        return this.state.model_fields.find(f => f.name === this.state.cf_field) || {};
    }

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.trendChartRef = useRef("trend_chart");
        this.journalChartRef = useRef("journal_chart");
        this.inboundChartRef = useRef("inbound_chart");
        this.outboundChartRef = useRef("outbound_chart");
        this.dynamicChartRef = useRef("dynamic_chart");
        this.pillarsChartRef = useRef("pillars_chart"); // NEW REF

        const savedState = JSON.parse(localStorage.getItem('wb_cashflow_dashboard_state')) || {};
        const savedFavorites = JSON.parse(localStorage.getItem('cashflow_dashboard_favorites')) || [];
        const defaultFav = savedFavorites.find(f => f.is_default === true);

        this.state = useState({
            showSidebar: true,
            period: String(savedState.period || "30"), date_from: savedState.date_from || "", date_to: savedState.date_to || "",
            journal_id: String(savedState.journal_id || "all"), payment_type: String(savedState.payment_type || "all"),
            partner_type: String(savedState.partner_type || "all"),

            filter_journals: [], filter_companies: [], model_fields: [],

            total_cash_in: 0, total_cash_out: 0, net_cash_flow: 0, total_transactions: 0, avg_transaction_value: 0, nav_domain: [],

            // NEW METRICS
            cfo: 0, cfi: 0, cff: 0, quality_of_income: 0, coverage_ratio: 0,

            trend_labels: [], trend_in: [], trend_out: [], trend_net: [],
            journal_labels: [], journal_data: [],
            inbound_partner_labels: [], inbound_partner_data: [],
            outbound_partner_labels: [], outbound_partner_data: [],
            dynamic_chart_labels: [], dynamic_chart_data: [],

            search_query: defaultFav ? defaultFav.search_query : (savedState.search_query || ''),
            active_filters: defaultFav ? { ...defaultFav.active_filters } : (savedState.active_filters || { internal_transfers: false }),
            custom_domain: defaultFav ? [...defaultFav.custom_domain] : (savedState.custom_domain || []),
            group_by_list: defaultFav ? [...defaultFav.group_by_list] : (savedState.group_by_list || []),

            show_custom_filter_menu: false, cf_field: '', cf_operator: '=', cf_value: '',
            show_custom_group_menu: false, cg_field: '',

            active_favorite_name: defaultFav ? defaultFav.name : null, saved_favorites: savedFavorites,
            show_save_menu: false, favorite_name: 'Cash Flow Analytics', is_default_fav: false,

            showExportModal: false, showPdfModal: false, export_group: "journal_id", detailed_excel: false,
            meas_in: true, meas_out: true, meas_net: true,
            pdf_kpis: true, pdf_ratios: true
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
            if (this.journalChartRef.el?.chartInstance) this.journalChartRef.el.chartInstance.destroy();
            if (this.inboundChartRef.el?.chartInstance) this.inboundChartRef.el.chartInstance.destroy();
            if (this.outboundChartRef.el?.chartInstance) this.outboundChartRef.el.chartInstance.destroy();
            if (this.dynamicChartRef.el?.chartInstance) this.dynamicChartRef.el.chartInstance.destroy();
            if (this.pillarsChartRef.el?.chartInstance) this.pillarsChartRef.el.chartInstance.destroy();
        });
    }

    async loadFilters() {
        const data = await this.orm.call("wb.cashflow.dashboard", "get_filter_options", []);
        if (data) {
            this.state.filter_journals = data.journals || []; this.state.model_fields = data.model_fields || [];
            if(this.state.model_fields.length > 0) {
                this.state.cf_field = this.state.model_fields[0].name;
                this.state.cg_field = this.state.model_fields[0].name;
            }
        }
    }

    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }
    async applyDateFilter() { if (this.state.date_from && this.state.date_to) { this.state.period = "0"; await this.fetchData(); } }
    async onChangePeriod() { this.state.date_from = ""; this.state.date_to = ""; await this.fetchData(); }
    async onChangeFilter() { await this.fetchData(); }

    async onSearchKeyUp(ev) {
        if (ev.key === 'Enter' && ev.target.value.trim() !== '') {
            this.state.active_favorite_name = null; this.state.search_query = ev.target.value; ev.target.value = ''; await this.fetchData();
        }
    }
    async clearSearchQuery() { this.state.active_favorite_name = null; this.state.search_query = ''; await this.fetchData(); }
    async toggleFilter(filterName) { this.state.active_favorite_name = null; this.state.active_filters[filterName] = !this.state.active_filters[filterName]; await this.fetchData(); }

    toggleCustomFilterMenu(ev) { ev.stopPropagation(); this.state.show_custom_filter_menu = !this.state.show_custom_filter_menu; }
    async addCustomFilter(ev) {
        ev.stopPropagation();
        if(this.state.cf_field && this.state.cf_value !== '') {
            const fieldObj = this.state.model_fields.find(f => f.name === this.state.cf_field);
            this.state.custom_domain.push({ field: this.state.cf_field, label: fieldObj ? fieldObj.string : this.state.cf_field, operator: this.state.cf_operator, value: this.state.cf_value, type: fieldObj ? fieldObj.type : 'char' });
            this.state.active_favorite_name = null; this.state.cf_value = ''; this.state.show_custom_filter_menu = false; await this.fetchData();
        }
    }
    async removeCustomFilter(index) { this.state.custom_domain.splice(index, 1); await this.fetchData(); }

    toggleCustomGroupMenu(ev) { ev.stopPropagation(); this.state.show_custom_group_menu = !this.state.show_custom_group_menu; }
    async addCustomGroupBy(ev) {
        ev.stopPropagation();
        if(this.state.cg_field && !this.state.group_by_list.includes(this.state.cg_field)) {
            this.state.group_by_list.push(this.state.cg_field); this.state.show_custom_group_menu = false; await this.fetchData();
        }
    }
    async toggleGroupBy(groupName) {
        if (this.state.group_by_list.includes(groupName)) this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        else this.state.group_by_list.push(groupName); await this.fetchData();
    }
    async removeGroupBy(groupName) { this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName); await this.fetchData(); }

    toggleSaveMenu(ev) { ev.stopPropagation(); this.state.show_save_menu = !this.state.show_save_menu; }
    saveFavoriteUI(ev) {
        ev.stopPropagation();
        if (this.state.favorite_name.trim()) {
            if (this.state.is_default_fav) this.state.saved_favorites.forEach(f => f.is_default = false);
            this.state.saved_favorites.push({ id: Date.now(), name: this.state.favorite_name, search_query: this.state.search_query, active_filters: { ...this.state.active_filters }, custom_domain: [...this.state.custom_domain], group_by_list: [...this.state.group_by_list], is_default: this.state.is_default_fav });
            localStorage.setItem('cashflow_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
            this.state.show_save_menu = false; this.state.favorite_name = 'Cash Flow Analytics'; this.state.is_default_fav = false;
        }
    }
    loadFavorite(fav) { this.state.search_query = fav.search_query; this.state.active_filters = { ...fav.active_filters }; this.state.custom_domain = [...fav.custom_domain]; this.state.group_by_list = [...fav.group_by_list]; this.state.active_favorite_name = fav.name; this.fetchData(); }
    async clearFavorite() { this.state.active_favorite_name = null; this.state.search_query = ''; this.state.active_filters = { internal_transfers: false }; this.state.custom_domain = []; this.state.group_by_list = []; await this.fetchData(); }
    deleteFavorite(favId) { this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== favId); localStorage.setItem('cashflow_dashboard_favorites', JSON.stringify(this.state.saved_favorites)); }

    async fetchData() {
        const kwargs = {
            journal_id: this.state.journal_id, payment_type: this.state.payment_type, partner_type: this.state.partner_type,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            search_query: this.state.search_query, active_filters: this.state.active_filters, custom_domain: this.state.custom_domain, group_by_list: this.state.group_by_list
        };
        const data = await this.orm.call("wb.cashflow.dashboard", "get_cashflow_dashboard_data", [], kwargs);
        if (data) {
            Object.assign(this.state, data); this.renderCharts();
            localStorage.setItem('wb_cashflow_dashboard_state', JSON.stringify(kwargs));
        }
    }

    openRecords(type) {
        let domain = [...this.state.nav_domain];
        if (type === 'inbound') domain.push(['payment_type', '=', 'inbound']);
        if (type === 'outbound') domain.push(['payment_type', '=', 'outbound']);
        this.action.doAction({ name: "Cash Flow Records", type: "ir.actions.act_window", res_model: "account.payment", view_mode: "list,form", views: [[false, "list"], [false, "form"]], domain: domain });
    }

    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    openPdfModal() { this.state.showPdfModal = true; }
    closePdfModal() { this.state.showPdfModal = false; }

    async downloadCustomExcel() {
        this.state.showExportModal = false;
        const kwargs = { export_group: this.state.export_group, detailed_excel: this.state.detailed_excel, ...this.state };
        const attachmentId = await this.orm.call("wb.cashflow.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const element = document.getElementById('print_report_area'); element.style.display = 'block';
        window.html2pdf().set({ margin: 0.5, filename: `CashFlow_Report_${new Date().toISOString().split('T')[0]}.pdf`, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' } }).from(element).save().then(() => { element.style.display = 'none'; });
    }

    renderCharts() {
        this._renderChart(this.trendChartRef, 'line', this.state.trend_labels, [
            { label: 'Cash Inbound', data: this.state.trend_in, borderColor: '#10b981', backgroundColor: '#10b981', tension: 0.4 },
            { label: 'Cash Outbound', data: this.state.trend_out, borderColor: '#ef4444', backgroundColor: '#ef4444', tension: 0.4 },
            { label: 'Net Cash Flow', data: this.state.trend_net, borderColor: '#3b82f6', backgroundColor: '#3b82f6', borderDash: [5, 5], tension: 0.4 }
        ]);

        this._renderChart(this.inboundChartRef, 'bar', this.state.inbound_partner_labels, [
            { label: 'Received From (EGP)', data: this.state.inbound_partner_data, backgroundColor: '#10b981', borderRadius: 4 }
        ], 'y');

        this._renderChart(this.outboundChartRef, 'bar', this.state.outbound_partner_labels, [
            { label: 'Paid To (EGP)', data: this.state.outbound_partner_data, backgroundColor: '#ef4444', borderRadius: 4 }
        ], 'y');

        this._renderDoughnut(this.journalChartRef, this.state.journal_labels, this.state.journal_data, ['#4f46e5', '#f59e0b', '#06b6d4', '#8b5cf6']);

        if (this.state.group_by_list && this.state.group_by_list.length > 0) {
            this._renderChart(this.dynamicChartRef, 'bar', this.state.dynamic_chart_labels, [
                { label: 'Grouped Net Impact', data: this.state.dynamic_chart_data, backgroundColor: '#8b5cf6', borderRadius: 4 }
            ]);
        } else if (this.dynamicChartRef.el?.chartInstance) {
            this.dynamicChartRef.el.chartInstance.destroy();
        }

        // NEW: Render Pillars Chart
        const pillarData = [this.state.cfo, this.state.cfi, this.state.cff];
        this._renderChart(this.pillarsChartRef, 'bar', ['Operating (CFO)', 'Investing (CFI)', 'Financing (CFF)'], [{
            label: 'Cash Flow Impact (EGP)',
            data: pillarData,
            backgroundColor: pillarData.map(v => v >= 0 ? '#10b981' : '#ef4444'),
            borderRadius: 6
        }]);
    }

    _renderChart(ref, type, labels, datasets, indexAxis = 'x') {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: type, data: { labels: labels, datasets: datasets }, options: { indexAxis: indexAxis, responsive: true, maintainAspectRatio: false } });
    }

    _renderDoughnut(ref, labels, data, colors) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, { type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, hoverOffset: 4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } } });
    }
}
registry.category("actions").add("cashflow_dashboard_client_tag", CashFlowDashboardClient);