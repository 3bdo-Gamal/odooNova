/** @odoo-module */
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, useRef, useSubEnv } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { SearchModel } from "@web/search/search_model";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class PurchaseBillsDashboard extends Component {
    static template = "purchase_bills_dashboard_template";
    static components = { SearchBar };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.viewService = useService("view");

        this.chartRefs = {
            chart_trend: useRef("chart_trend"),
            chart_status: useRef("chart_status"),
            chart_vendor: useRef("chart_vendor"),
            chart_lead_time: useRef("chart_lead_time"),
            chart_price_var: useRef("chart_price_var")
        };

        this.filterRefs = {
            date_from: useRef("date_from"),
            date_to: useRef("date_to")
        };

        this.chartInstances = {};

        let savedState = {};
        try {
            const storedState = localStorage.getItem('wb_purchase_dashboard_state');
            if (storedState) {
                savedState = JSON.parse(storedState);
            }
        } catch (e) {
            console.warn('Failed to parse saved dashboard state:', e);
            savedState = {};
        }

        this.state = useState({
            showSidebar: true,
            showExportModal: false,

            filter_options: {
                vendors: [],
                journals: [],
                payment_terms: [],
                categories: [],
                locations: []
            },

            filters: {
                vendor_id: savedState.vendor_id || "all",
                journal_id: savedState.journal_id || "all",
                payment_term_id: savedState.payment_term_id || "all",
                category_id: savedState.category_id || "all",
                location_id: savedState.location_id || "all"
            },

            period: savedState.period || "30",
            date_from: savedState.date_from || "",
            date_to: savedState.date_to || "",

            kpi_data: {
                cards: {
                    total_bills_count: 0,
                    total_bills_amount: "$0",
                    upcoming_payables: "$0",
                    avg_dpo: 0,
                    late_bills_ratio: 0,
                    wo_po_ratio: 0,
                    wo_po_count: 0
                },
                tables: { qty_variance_pivot: [] },
                charts: { trend: {}, status: {}, vendor: {}, lead_time: {}, price_var: {} }
            },

            active_filters: {
                state_posted: savedState.hasOwnProperty('state_posted') ? savedState.state_posted : true,
                state_draft: savedState.state_draft || false,
                pay_not_paid: savedState.pay_not_paid || false,
                pay_paid: savedState.pay_paid || false,
                is_overdue: savedState.is_overdue || false,
                has_po: savedState.has_po || false,
                no_po: savedState.no_po || false
            }
        });

        this.searchModel = new SearchModel(this.env, {
            user: useService("user"),
            orm: this.orm,
            view: this.viewService
        });
        useSubEnv({ searchModel: this.searchModel });

        onWillStart(async () => {
            await Promise.all([
                loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"),
                loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js")
            ]);

            try {
                this.state.filter_options = await this.orm.call("wb.purchase.bills.dashboard", "get_filter_options", []);
            } catch (error) {
                console.error("Failed to load filter options:", error);
            }

            try {
                const views = await this.orm.call("account.move", "get_views", [], {
                    views: [[false, "search"]],
                    options: { toolbar: false, action_id: false },
                    context: { default_move_type: 'in_invoice' }
                });

                await this.searchModel.load({
                    resModel: "account.move",
                    context: { default_move_type: 'in_invoice' },
                    searchViewId: views.views.search.id,
                    searchViewArch: views.views.search.arch,
                    searchViewFields: views.models["account.move"],
                    searchMenuTypes: ["filter", "favorite"]
                });

                this.searchModel.addEventListener("update", () => {
                    this.fetchData();
                });
            } catch (error) {
                console.error("Search model initialization error:", error);
            }

            await this.fetchData();
        });

       onMounted(() => {
            if (this.state.period === "0") {
                 if (this.filterRefs.date_from.el) this.filterRefs.date_from.el.value = this.state.date_from || "";
                 if (this.filterRefs.date_to.el) this.filterRefs.date_to.el.value = this.state.date_to || "";
            }

            setTimeout(() => {
                if (this.state.kpi_data && this.state.kpi_data.charts) {
                    this.renderCharts();
                }
            }, 50);
        });
    }

    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }
    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    async applyDateFilter() { this.state.period = "0"; await this.onApplyFilter(); }

    async onChangePeriod() {
        this.state.date_from = "";
        this.state.date_to = "";
        if (this.filterRefs.date_from.el) this.filterRefs.date_from.el.value = "";
        if (this.filterRefs.date_to.el) this.filterRefs.date_to.el.value = "";
        await this.onApplyFilter();
    }

    async toggleFilter(filterName) {
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
        await this.onApplyFilter();
    }

    async onApplyFilter() {
        try {
            localStorage.setItem('wb_purchase_dashboard_state', JSON.stringify(this.state));
        } catch (e) {
            console.warn('Failed to save dashboard state:', e);
        }
        await this.fetchData();
    }

    async resetFilters() {
        this.state.period = "30";
        this.state.date_from = "";
        this.state.date_to = "";

        this.state.filters = { vendor_id: "all", journal_id: "all", payment_term_id: "all", category_id: "all", location_id: "all" };
        this.state.active_filters = { state_posted: true, state_draft: false, pay_not_paid: false, pay_paid: false, is_overdue: false, has_po: false, no_po: false };

        if (this.filterRefs.date_from.el) this.filterRefs.date_from.el.value = "";
        if (this.filterRefs.date_to.el) this.filterRefs.date_to.el.value = "";

        try { localStorage.removeItem('wb_purchase_dashboard_state'); } catch (e) {}
        await this.fetchData();
    }

    async fetchData() {
        const searchDomain = (this.env.searchModel && this.env.searchModel.domain) ? this.env.searchModel.domain : [];
        try {
            const kwargs = {
                period: parseInt(this.state.period) || 0, date_from: this.state.date_from || false, date_to: this.state.date_to || false,
                vendor_id: this.state.filters.vendor_id, journal_id: this.state.filters.journal_id, payment_term_id: this.state.filters.payment_term_id,
                category_id: this.state.filters.category_id, location_id: this.state.filters.location_id,
                active_filters: this.state.active_filters, native_domain: searchDomain
            };

            const data = await this.orm.call("wb.purchase.bills.dashboard", "get_dashboard_data", [], kwargs);
            if (data) {
                this.state.kpi_data = data;
                setTimeout(() => { this.renderCharts(); }, 50);
            }
        } catch (error) { console.error("Error fetching data:", error); }
    }

    async downloadExcel() {
        this.state.showExportModal = false;
        const searchDomain = (this.env.searchModel && this.env.searchModel.domain) ? this.env.searchModel.domain : [];
        try {
            const attachmentId = await this.orm.call("wb.purchase.bills.dashboard", "export_bills_excel", [], {
                period: parseInt(this.state.period) || 0, date_from: this.state.date_from || "", date_to: this.state.date_to || "",
                vendor_id: this.state.filters.vendor_id, journal_id: this.state.filters.journal_id, payment_term_id: this.state.filters.payment_term_id,
                category_id: this.state.filters.category_id, location_id: this.state.filters.location_id,
                active_filters: this.state.active_filters, native_domain: searchDomain
            });
            if (attachmentId) { window.location = `/web/content/${attachmentId}?download=true`; }
        } catch (error) { console.error(error); }
    }

    printPDF() {
        const element = document.getElementById('print_report_area');
        if (!element) return;
        element.style.display = 'block';
        window.html2pdf().set({ margin: 0.5, filename: `Purchase_Bills_Report.pdf`, image: { type: 'jpeg', quality: 0.98 }, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' } }).from(element).save().then(() => { element.style.display = 'none'; });
    }

    renderCharts() {
        Object.values(this.chartInstances).forEach(chart => { if (chart) chart.destroy(); });
        const chartsData = this.state.kpi_data.charts || {};
        const barOptions = { barPercentage: 0.4, categoryPercentage: 0.5 };

        if (this.chartRefs.chart_trend.el && chartsData.trend && chartsData.trend.labels && chartsData.trend.labels.length > 0) {
             this.chartInstances.trend = new window.Chart(this.chartRefs.chart_trend.el, { type: 'line', data: chartsData.trend, options: { responsive: true, maintainAspectRatio: false, onClick: () => this.openAction('trend') } });
        }
        if (this.chartRefs.chart_status.el && chartsData.status && chartsData.status.labels && chartsData.status.labels.length > 0) {
            this.chartInstances.status = new window.Chart(this.chartRefs.chart_status.el, { type: 'doughnut', data: chartsData.status, options: { responsive: true, maintainAspectRatio: false, onClick: (ev, elements) => { if (elements.length > 0) { const label = chartsData.status.labels[elements[0].index]; this.openAction('status', label === 'Paid' ? 'paid' : 'unpaid'); } } } });
        }
        if (this.chartRefs.chart_vendor.el && chartsData.vendor && chartsData.vendor.labels && chartsData.vendor.labels.length > 0) {
            this.chartInstances.vendor = new window.Chart(this.chartRefs.chart_vendor.el, { type: 'bar', data: chartsData.vendor, options: { responsive: true, maintainAspectRatio: false, datasets: { bar: barOptions }, onClick: () => this.openAction('vendor') } });
        }
        if (this.chartRefs.chart_lead_time.el && chartsData.lead_time && chartsData.lead_time.labels && chartsData.lead_time.labels.length > 0) {
            this.chartInstances.lead_time = new window.Chart(this.chartRefs.chart_lead_time.el, { type: 'bar', data: chartsData.lead_time, options: { responsive: true, maintainAspectRatio: false, datasets: { bar: barOptions }, onClick: () => this.openAction('lead_time') } });
        }
        if (this.chartRefs.chart_price_var.el && chartsData.price_var && chartsData.price_var.labels && chartsData.price_var.labels.length > 0) {
            this.chartInstances.price_var = new window.Chart(this.chartRefs.chart_price_var.el, { type: 'bar', data: chartsData.price_var, options: { responsive: true, maintainAspectRatio: false, datasets: { bar: barOptions }, onClick: () => this.openAction('price_var') } });
        }
    }

 async openAction(actionType, subType = null) {
        let domain = [['move_type', '=', 'in_invoice']];
        let name = "Bills Analysis";
        let res_model = 'account.move';
        let view_mode = 'list,form';
        let context = {};
        let target_view_name = '';

        const dateFrom = this.state.date_from || false;
        const dateTo = this.state.date_to || false;

        switch (actionType) {
            case 'all':
                domain.push(['state', '=', 'posted']);
                name = "Posted Purchase Bills (Total Amount)";
                target_view_name = 'dashboard.bills.default.tree.v2';
                break;
            case 'all_count':
                name = "All Purchase Bills";
                target_view_name = 'dashboard.bills.default.tree.v2';
                break;
            case 'upcoming':
                domain.push(['state', '=', 'posted'], ['payment_state', 'in', ['not_paid', 'partial']], ['invoice_date_due', '>=', new Date().toISOString().split('T')[0]]);
                name = "Upcoming Payables";
                target_view_name = 'dashboard.bills.upcoming.tree.v2';
                break;
            case 'late_bills':
                domain.push(['state', '=', 'posted'], ['payment_state', 'in', ['not_paid', 'partial']], ['invoice_date_due', '<', new Date().toISOString().split('T')[0]]);
                name = "Overdue Vendor Bills";
                target_view_name = 'dashboard.bills.upcoming.tree.v2';
                break;
            case 'dpo':
                domain.push(['state', '=', 'posted']);
                name = "Average Days Outstanding Payables (DOP)";
                target_view_name = 'dashboard.bills.dpo.tree.v2';
                break;
            case 'status':
                if (subType === 'paid') {
                    domain.push(['payment_state', '=', 'paid']);
                    name = "Paid Vendor Bills";
                } else {
                    domain.push(['state', '=', 'posted'], ['payment_state', 'in', ['not_paid', 'partial']]);
                    name = "Unpaid Vendor Bills";
                }
                target_view_name = 'dashboard.bills.default.tree.v2';
                break;
            case 'price_var':
                domain.push(['invoice_line_ids.purchase_line_id', '!=', false]);
                name = "Price Variance Analysis (PO vs Bill)";
                target_view_name = 'dashboard.bills.price.var.tree.v2';
                break;
            case 'wo_po':
                domain.push(['invoice_line_ids.purchase_line_id', '=', false]);
                name = "Vendor Bills Without PO (Maverick Spend)";
                target_view_name = 'dashboard.bills.default.tree.v2';
                break;
            case 'qty_variance_pivot':
                res_model = 'account.move.line';
                domain = [['move_id.move_type', '=', 'in_invoice'], ['purchase_line_id', '!=', false], ['display_type', '=', 'product']];
                name = "Quantity Variance Records";
                target_view_name = 'dashboard.lines.qty.var.tree.v2'; // هنا تم إضافة الـ v2 لتخطي الكاش
                break;
            case 'vendor':
                view_mode = 'graph,pivot,list';
                name = "Vendor Spending Analysis";
                context = { 'graph_measure': 'amount_total', 'graph_groupbys': ['partner_id'] };
                break;
            case 'trend':
                domain.push(['payment_state', '=', 'paid']);
                view_mode = 'graph,pivot,list';
                name = "Spending Trend Over Time (Paid Bills)";
                context = { 'graph_measure': 'amount_total', 'graph_groupbys': ['invoice_date:month'] };
                break;
            case 'lead_time':
                domain.push(['payment_state', '=', 'paid']);
                name = "Vendor Payment Lead Time Records";
                target_view_name = 'dashboard.bills.lead.time.tree.v2';
                context = { 'search_default_groupby_vendor': 1 };
                break;
        }

        if (res_model === 'account.move') {
            if (this.state.period && this.state.period !== "0") {
                const today = new Date();
                const pastDate = new Date(today.getTime() - (parseInt(this.state.period) * 24 * 60 * 60 * 1000));
                domain.push(['invoice_date', '>=', pastDate.toISOString().split('T')[0]], ['invoice_date', '<=', today.toISOString().split('T')[0]]);
            } else {
                if (dateFrom) domain.push(['invoice_date', '>=', dateFrom]);
                if (dateTo) domain.push(['invoice_date', '<=', dateTo]);
            }
        } else if (res_model === 'account.move.line') {
            if (this.state.period && this.state.period !== "0") {
                const today = new Date();
                const pastDate = new Date(today.getTime() - (parseInt(this.state.period) * 24 * 60 * 60 * 1000));
                domain.push(['move_id.invoice_date', '>=', pastDate.toISOString().split('T')[0]], ['move_id.invoice_date', '<=', today.toISOString().split('T')[0]]);
            } else {
                if (dateFrom) domain.push(['move_id.invoice_date', '>=', dateFrom]);
                if (dateTo) domain.push(['move_id.invoice_date', '<=', dateTo]);
            }
        }

        if (this.state.filters.vendor_id !== "all") {
            domain.push(res_model === 'account.move' ? ['partner_id', '=', parseInt(this.state.filters.vendor_id)] : ['move_id.partner_id', '=', parseInt(this.state.filters.vendor_id)]);
        }
        if (this.state.filters.journal_id !== "all") {
            domain.push(res_model === 'account.move' ? ['journal_id', '=', parseInt(this.state.filters.journal_id)] : ['move_id.journal_id', '=', parseInt(this.state.filters.journal_id)]);
        }
        if (this.state.filters.payment_term_id !== "all") {
            domain.push(res_model === 'account.move' ? ['invoice_payment_term_id', '=', parseInt(this.state.filters.payment_term_id)] : ['move_id.invoice_payment_term_id', '=', parseInt(this.state.filters.payment_term_id)]);
        }
        if (this.state.filters.category_id !== "all") {
            domain.push(res_model === 'account.move' ? ['invoice_line_ids.product_id.categ_id', 'child_of', parseInt(this.state.filters.category_id)] : ['product_id.categ_id', 'child_of', parseInt(this.state.filters.category_id)]);
        }
        if (this.state.filters.location_id !== "all") {
            domain.push(res_model === 'account.move' ? ['invoice_line_ids.purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of', parseInt(this.state.filters.location_id)] : ['purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of', parseInt(this.state.filters.location_id)]);
        }

        const applyQuickFilters = !['dpo', 'qty_variance_pivot'].includes(actionType);

        if (applyQuickFilters && res_model === 'account.move') {
            const states = [];
            if (!['upcoming', 'late_bills', 'status', 'all'].includes(actionType)) {
                if (this.state.active_filters.state_posted) states.push('posted');
                if (this.state.active_filters.state_draft) states.push('draft');
                if (states.length > 0) domain.push(['state', 'in', states]);
            }

            if (!['status', 'upcoming', 'late_bills', 'trend', 'lead_time'].includes(actionType)) {
                const payments = [];
                if (this.state.active_filters.pay_paid) payments.push('paid');
                if (this.state.active_filters.pay_not_paid) payments.push('not_paid', 'partial');
                if (payments.length > 0) domain.push(['payment_state', 'in', payments]);
            }

            if (!['late_bills', 'upcoming', 'trend', 'status'].includes(actionType) && this.state.active_filters.is_overdue) {
                domain.push(['state', '=', 'posted'], ['invoice_date_due', '<', new Date().toISOString().split('T')[0]], ['payment_state', 'in', ['not_paid', 'partial']]);
            }

            if (!['wo_po', 'price_var', 'qty_variance_pivot'].includes(actionType)) {
                const has_po = this.state.active_filters.has_po;
                const no_po = this.state.active_filters.no_po;
                if (has_po && !no_po) domain.push(['invoice_line_ids.purchase_line_id', '!=', false]);
                else if (no_po && !has_po) domain.push(['invoice_line_ids.purchase_line_id', '=', false]);
            }
        }

        const searchDomain = (this.env.searchModel && this.env.searchModel.domain) ? this.env.searchModel.domain : [];
        if (searchDomain.length > 0) {
            domain = domain.concat(searchDomain);
        }

        let list_view_id = false;
        if (target_view_name) {
            try {
                // سيبحث عن الـ Name الجديد (v2) الذي أنشأناه للتو
                const views = await this.orm.searchRead('ir.ui.view', [['name', '=', target_view_name]], ['id'], { limit: 1 });
                if (views.length > 0) {
                    list_view_id = views[0].id;
                }
            } catch (error) {
                console.warn("Could not fetch custom view:", error);
            }
        }

        let views_array = [];
        if (view_mode === 'list,form') {
            views_array = [[list_view_id, 'list'], [false, 'form']];
        } else if (view_mode === 'graph,pivot,list') {
            views_array = [[false, 'graph'], [false, 'pivot'], [list_view_id, 'list']];
        } else {
            views_array = view_mode.split(',').map(v => [false, v]);
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: res_model,
            view_mode: view_mode,
            views: views_array,
            domain: domain,
            context: context,
            target: 'current'
        });
    }
}

PurchaseBillsDashboard.template = "purchase_bills_dashboard_template";
registry.category("actions").add("purchase_bills_dashboard_tag", PurchaseBillsDashboard);