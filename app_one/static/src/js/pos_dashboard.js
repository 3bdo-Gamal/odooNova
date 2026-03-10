/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef, useSubEnv } from "@odoo/owl";
import { SearchModel } from "@web/search/search_model";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class PosDashboardClient extends Component {
    static template = "PosDashboardClientTemplate";
    static components = { SearchBar };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.viewService = useService("view");

        // ربط الرسومات البيانية الخاصة بالـ POS
        this.hourlyChartRef = useRef("hourly_chart");
        this.productChartRef = useRef("product_chart");


        this.state = useState({
            showSidebar: true,
            top_products: "5",
            state: "all", user_id: "all", config_id: "all", category_id: "all", company_id: "all",
            period: "7", date_from: "", date_to: "",

            filter_configs: [], filter_users: [], filter_categories: [], filter_companies: [],

            // POS KPIs
            pos_revenue: 0, pos_orders_count: 0, aov: 0,
            cash_ratio: 0, card_ratio: 0, discount_pct: 0, refund_rate: 0,


            filter_payment_methods: [],
            payment_method_id: "all",

            nav_domain: [],

            // Charts Data
            hourly_labels: [], hourly_data: [],
            product_labels: [], product_data: [],

            showExportModal: false, showPdfModal: false, export_group: "config_id", detailed_excel: false,
            meas_revenue: true, meas_qty: true, meas_discount: false,
            pdf_revenue: true, pdf_orders: true, pdf_ratios: true
        });

        this.searchModel = new SearchModel(this.env, { user: useService("user"), orm: this.orm, view: this.viewService });
        useSubEnv({ searchModel: this.searchModel });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();

            try {
                // نغير الموديل لـ pos.order عشان الـ Search Bar يشتغل صح
                const views = await this.orm.call("pos.order", "get_views", [], { views: [[false, "search"]], options: { toolbar: false, action_id: false } });
                await this.searchModel.load({ resModel: "pos.order", context: {}, searchViewId: views.views.search.id, searchViewArch: views.views.search.arch, searchViewFields: views.models["pos.order"] });
                this.searchModel.addEventListener("update", () => { this.fetchData(); });
            } catch (error) { console.error("Failed to load search model:", error); }
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async loadFilters() {
        try {
            const data = await this.orm.call("wb.pos.dashboard", "get_filter_options", []);
            if (data) {
                this.state.filter_configs = data.pos_configs || [];
                this.state.filter_users = data.users || [];
                this.state.filter_categories = data.categories || [];
                this.state.filter_companies = data.companies || [];
                this.state.filter_payment_methods = data.payment_methods || [];
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
            state: this.state.state, user_id: this.state.user_id, config_id: this.state.config_id,
            category_id: this.state.category_id, company_id: this.state.company_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            top_products: this.state.top_products, native_domain: searchDomain,
            payment_method_id: this.state.payment_method_id,
        };
        const data = await this.orm.call("wb.pos.dashboard", "get_pos_dashboard_data", [], kwargs);
        if (data) {
            Object.assign(this.state, data);
            this.state.aov = this.state.pos_orders_count > 0 ? (this.state.pos_revenue / this.state.pos_orders_count).toFixed(2) : 0;
            this.renderCharts();
        }
    }

    // فتح شاشة الـ POS بدل المبيعات
    openRecords(type) {
        let domain = [...this.state.nav_domain];
        if (this.state.state !== 'all') domain.push(['state', '=', this.state.state]);
        else domain.push(['state', '!=', 'cancel']);

        // لو داس على المرتجعات نفلتر الطلبات اللي بالسالب
        if (type === 'refunds') domain.push(['amount_total', '<', 0]);

        this.action.doAction({
            name: "POS Orders",
            type: "ir.actions.act_window",
            res_model: "pos.order",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain
        });
    }

    // Drill down للـ Charts
    openChartRecords(type, label) {
        if (!label || label === 'Unknown' || label === 'Uncategorized') return;
        let domain = [...this.state.nav_domain];
        if (this.state.state !== 'all') domain.push(['state', '=', this.state.state]);
        else domain.push(['state', '!=', 'cancel']);

        if (type === 'product') domain.push(['lines.product_id.name', '=', label]);
        // مفيش drill down مباشر للساعة في الـ ORM العادي بتاع أودو بسهولة، فممكن نتجاهلها هنا

        this.action.doAction({
            name: `Records for ${label}`,
            type: "ir.actions.act_window",
            res_model: "pos.order",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
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
        if (this.state.meas_revenue) measures.push('revenue');
        if (this.state.meas_qty) measures.push('qty');
        if (this.state.meas_discount) measures.push('discount');
        if (measures.length === 0) { alert("Please select at least one measure."); return; }

        const searchDomain = this.env.searchModel ? this.env.searchModel.domain : [];
        const kwargs = {
            state: this.state.state, user_id: this.state.user_id, config_id: this.state.config_id,payment_method_id: this.state.payment_method_id,
            category_id: this.state.category_id, company_id: this.state.company_id,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures, detailed_excel: this.state.detailed_excel, native_domain: searchDomain
        };
        const attachmentId = await this.orm.call("wb.pos.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const element = document.getElementById('print_report_area'); element.style.display = 'block';
        const opt = { margin: 0.5, filename: `POS_KPI_Report_${new Date().toISOString().split('T')[0]}.pdf`, image: { type: 'jpeg', quality: 0.98 }, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' } };
        window.html2pdf().set(opt).from(element).save().then(() => { element.style.display = 'none'; });
    }

    renderCharts() {
        this._renderChart(this.hourlyChartRef, 'bar', this.state.hourly_labels, this.state.hourly_data, '#3b82f6', 'Revenue per Hour', 'hourly');
        this._renderDoughnut(this.productChartRef, this.state.product_labels, this.state.product_data, ['#4f46e5', '#10b981', '#06b6d4', '#f59e0b', '#ef4444'], 'product');
    }

    _renderChart(ref, type, labels, data, color, label, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: type, data: { labels: labels, datasets: [{ label: label, data: data, backgroundColor: color, borderColor: color, fill: type === 'line', tension: 0.4, borderRadius: type === 'bar' ? 4 : 0 }] },
            options: { responsive: true, maintainAspectRatio: false, onClick: (e, activeEls) => { if (activeEls.length > 0 && clickType !== 'hourly') this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } }
        });
    }

    _renderDoughnut(ref, labels, data, colors, clickType) {
        if (!ref.el) return; if (ref.el.chartInstance) ref.el.chartInstance.destroy();
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: 'doughnut', data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, hoverOffset: 4 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, onClick: (e, activeEls) => { if (activeEls.length > 0) this.openChartRecords(clickType, labels[activeEls[0].index]); }, onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? 'pointer' : 'default'; } }
        });
    }
}
registry.category("actions").add("pos_dashboard_client_tag", PosDashboardClient);