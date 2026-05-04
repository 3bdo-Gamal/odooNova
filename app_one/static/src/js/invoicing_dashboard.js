/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef, useSubEnv } from "@odoo/owl";
import { SearchModel } from "@web/search/search_model";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class InvoicingDashboardClient extends Component {
    static template = "InvoicingDashboardClientTemplate";
    static components = { SearchBar };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.viewService = useService("view");

        this.trendChartRef = useRef("trend_chart");
        this.customerChartRef = useRef("customer_chart");
        this.statusChartRef = useRef("status_chart");

        this.state = useState({
            showSidebar: true,
            period: "30", date_from: "", date_to: "",
            journal_id: "all", user_id: "all", company_id: "all", payment_state: "all",

            filter_journals: [], filter_users: [], filter_companies: [],

            // Invoicing KPIs
            total_invoiced_amount: 0, cash_collected: 0, unpaid_amount: 0,
            paid_ratio: 0, unpaid_ratio: 0, overdue_amount: 0,
            overdue_rate: 0, dso: 0, bad_debt_pct: 0,

            nav_domain: [],

            // Charts Data
            trend_labels: [], trend_invoiced_data: [], trend_collected_data: [],
            customer_labels: [], customer_data: [],

            // Export & Modal States
            showExportModal: false, showPdfModal: false, export_group: "journal_id", detailed_excel: false,
            meas_invoiced: true, meas_collected: true, meas_unpaid: false,
            pdf_invoiced: true, pdf_unpaid: true, pdf_ratios: true
        });

        this.searchModel = new SearchModel(this.env, { user: useService("user"), orm: this.orm, view: this.viewService });
        useSubEnv({ searchModel: this.searchModel });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();

            try {
                const views = await this.orm.call("account.move", "get_views", [], { views: [[false, "search"]], options: { toolbar: false, action_id: false } });
                await this.searchModel.load({ resModel: "account.move", context: {}, searchViewId: views.views.search.id, searchViewArch: views.views.search.arch, searchViewFields: views.models["account.move"] });
                this.searchModel.addEventListener("update", () => { this.fetchData(); });
            } catch (error) { console.error("Failed to load search model:", error); }
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async loadFilters() {
        try {
            const data = await this.orm.call("wb.invoicing.dashboard", "get_filter_options", []);
            if (data) {
                this.state.filter_journals = data.journals || [];
                this.state.filter_users = data.users || [];
                this.state.filter_companies = data.companies || [];
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
            journal_id: this.state.journal_id, user_id: this.state.user_id,
            company_id: this.state.company_id, payment_state: this.state.payment_state,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            native_domain: searchDomain
        };
        const data = await this.orm.call("wb.invoicing.dashboard", "get_invoicing_dashboard_data", [], kwargs);
        if (data) {
            Object.assign(this.state, data);
            this.renderCharts();
        }
    }

    openRecords(type) {
        let domain = [...this.state.nav_domain];
        if (type === 'unpaid') domain.push(['payment_state', 'in', ['not_paid', 'partial']]);
        if (type === 'overdue') {
            domain.push(['payment_state', 'in', ['not_paid', 'partial']]);
            domain.push(['invoice_date_due', '<', new Date().toISOString().split('T')[0]]);
        }

        this.action.doAction({
            name: "Invoices",
            type: "ir.actions.act_window",
            res_model: "account.move",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain
        });
    }

    // --- Export Functions ---
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

        const searchDomain = this.env.searchModel ? this.env.searchModel.domain : [];
        const kwargs = {
            journal_id: this.state.journal_id, user_id: this.state.user_id,
            company_id: this.state.company_id, payment_state: this.state.payment_state,
            period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
            export_group: this.state.export_group, export_measures: measures, detailed_excel: this.state.detailed_excel, native_domain: searchDomain
        };

        // Ensure your Python model implements `export_custom_pivot_excel`
        const attachmentId = await this.orm.call("wb.invoicing.dashboard", "export_custom_pivot_excel", [], kwargs);
        if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
    }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const element = document.getElementById('print_report_area');
        element.style.display = 'block';
        const opt = {
            margin: 0.5,
            filename: `Invoicing_KPI_Report_${new Date().toISOString().split('T')[0]}.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2 },
            jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' }
        };
        window.html2pdf().set(opt).from(element).save().then(() => { element.style.display = 'none'; });
    }

    renderCharts() {
        if (this.trendChartRef.el) {
            if (this.trendChartRef.el.chartInstance) this.trendChartRef.el.chartInstance.destroy();
            this.trendChartRef.el.chartInstance = new window.Chart(this.trendChartRef.el, {
                type: 'line',
                data: {
                    labels: this.state.trend_labels,
                    datasets: [
                        { label: 'Total Invoiced', data: this.state.trend_invoiced_data, borderColor: '#3b82f6', backgroundColor: '#3b82f6', tension: 0.4 },
                        { label: 'Cash Collected', data: this.state.trend_collected_data, borderColor: '#10b981', backgroundColor: '#10b981', tension: 0.4 }
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }

        if (this.customerChartRef.el) {
            if (this.customerChartRef.el.chartInstance) this.customerChartRef.el.chartInstance.destroy();
            this.customerChartRef.el.chartInstance = new window.Chart(this.customerChartRef.el, {
                type: 'bar',
                data: { labels: this.state.customer_labels, datasets: [{ label: 'Unpaid Amount (Debt)', data: this.state.customer_data, backgroundColor: '#4f46e5ff', borderRadius: 4 }] },
                options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false }
            });
        }

        if (this.statusChartRef.el) {
            if (this.statusChartRef.el.chartInstance) this.statusChartRef.el.chartInstance.destroy();
            this.statusChartRef.el.chartInstance = new window.Chart(this.statusChartRef.el, {
                type: 'doughnut',
                data: { labels: ['Paid', 'Unpaid'], datasets: [{ data: [this.state.cash_collected, this.state.unpaid_amount], backgroundColor: ['#10b981', '#f59e0b'] }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });
        }
    }
}
registry.category("actions").add("invoicing_dashboard_client_tag", InvoicingDashboardClient);   