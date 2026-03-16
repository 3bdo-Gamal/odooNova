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

        const savedState = JSON.parse(localStorage.getItem('wb_purchase_dashboard_state')) || {};

        this.state = useState({
            showSidebar: true,
            showExportModal: false,


            filter_options: { vendors: [], journals: [], categories: [], locations: [] },
            filters: {
                vendor_id: savedState.vendor_id || "all",
                journal_id: savedState.journal_id || "all",
                category_id: savedState.category_id || "all",
                location_id: savedState.location_id || "all"
            },
                period: "30", // (Last Month) Default value
    date_from: "",
    date_to: "",
    kpi_data: {
        cards: { total_bills_count: 0, total_bills_amount: "$0", upcoming_payables: "$0", avg_dpo: 0, late_bills_ratio: 0, wo_po_ratio: 0 },
        tables: { qty_variance_pivot: [] },
        charts: { trend: {}, status: {}, vendor: {}, lead_time: {}, price_var: {} }
    },
    active_filters: {
        state_posted: false, state_draft: false, pay_not_paid: false,
        pay_paid: false, is_overdue: false, has_po: false, no_po: false
    }
});



        // تفعيل الـ Search Model الأصلي لأودو (شريط البحث بالسهم والاقتراحات)
        this.searchModel = new SearchModel(this.env, { user: useService("user"), orm: this.orm, view: this.viewService });
        useSubEnv({ searchModel: this.searchModel });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");

            // جلب الموردين واليوميات من الداتا بيز
            this.state.filter_options = await this.orm.call("wb.purchase.bills.dashboard", "get_filter_options", []);

            try {
                // جلب الـ Search View الخاص بفواتير الموردين
                const views = await this.orm.call("account.move", "get_views", [], { views: [[false, "search"]], options: { toolbar: false, action_id: false } });

                // تنظيف الـ View من الجروب باي ليكون فلتر فقط
                let cleanSearchArch = views.views.search.arch.replace(/<group[^>]*>.*?<\/group>/gis, '').replace(/<filter [^>]*context="\{[^}]*'group_by'[^}]*\}"[^>]*\/>/gis, '');

                await this.searchModel.load({
                    resModel: "account.move",
                    context: { default_move_type: 'in_invoice' }, // التركيز على فواتير المشتريات فقط
                    searchViewId: views.views.search.id,
                    searchViewArch: cleanSearchArch,
                    searchViewFields: views.models["account.move"],
                    searchMenuTypes: ["filter"] // إظهار الفلاتر فقط في السهم الجانبي
                });

                // تحديث البيانات عند أي تغيير في شريط البحث
                this.searchModel.addEventListener("update", () => { this.fetchData(); });
            } catch (error) {
                console.error("Search model error:", error);
            }

            const today = new Date();
            const yyyy = today.getFullYear();
            let mm = today.getMonth() + 1;
            let dd = today.getDate();

            if (mm < 10) mm = '0' + mm;
            if (dd < 10) dd = '0' + dd;

            this.defaultDateFrom = `${yyyy}-01-01`;
            this.defaultDateTo = `${yyyy}-${mm}-${dd}`;

            await this.fetchData(this.defaultDateFrom, this.defaultDateTo);
        });

        onMounted(() => {
            if(this.filterRefs.date_from.el) this.filterRefs.date_from.el.value = this.defaultDateFrom;
            if(this.filterRefs.date_to.el) this.filterRefs.date_to.el.value = this.defaultDateTo;
            this.renderCharts();
        });
    }

    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }
    openExportModal() { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    async applyDateFilter() {
        this.state.period = "0"; // تصفير الـ Period عند استخدام التواريخ المخصصة
        await this.fetchData();
    }

    async onChangePeriod() {
        this.state.date_from = ""; // تصفير التواريخ المخصصة عند استخدام الـ Period
        this.state.date_to = "";
        await this.fetchData();
    }

    async toggleFilter(filterName) {
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
        await this.onApplyFilter();
    }

    async fetchData(dateFrom = null, dateTo = null) {

    const searchDomain = (this.env.searchModel && this.env.searchModel.domain) ? this.env.searchModel.domain : [];

    try {
        const kwargs = {
                period: parseInt(this.state.period) || 0,
                date_from: this.state.date_from || false,
                date_to: this.state.date_to || false,
                vendor_id: this.state.filters.vendor_id,
                journal_id: this.state.filters.journal_id,
                category_id: this.state.filters.category_id,
                location_id: this.state.filters.location_id,
                active_filters: this.state.active_filters,
                native_domain: searchDomain
        };

        const data = await this.orm.call("wb.purchase.bills.dashboard", "get_dashboard_data", [], kwargs);
        if (data) {
            this.state.kpi_data = data;
            this.renderCharts();
        }
    } catch (error) { console.error("Error:", error); }

        if(!dateFrom) dateFrom = this.filterRefs.date_from.el ? this.filterRefs.date_from.el.value : this.defaultDateFrom;
        if(!dateTo) dateTo = this.filterRefs.date_to.el ? this.filterRefs.date_to.el.value : this.defaultDateTo;


    }

    async onApplyFilter() {
        await this.fetchData();
    }

    async downloadExcel() {
        this.state.showExportModal = false;
        const dateFrom = this.filterRefs.date_from.el ? this.filterRefs.date_from.el.value : "";
        const dateTo = this.filterRefs.date_to.el ? this.filterRefs.date_to.el.value : "";
        const searchDomain = (this.env.searchModel && this.env.searchModel.domain) ? this.env.searchModel.domain : [];

        const attachmentId = await this.orm.call("wb.purchase.bills.dashboard", "export_bills_excel", [], {
            date_from: dateFrom,
            date_to: dateTo,
            vendor_id: this.state.filters.vendor_id,
            journal_id: this.state.filters.journal_id,
            active_filters: this.state.active_filters,
            native_domain: searchDomain
        });

        if (attachmentId) {
            window.location = `/web/content/${attachmentId}?download=true`;
        }
    }

    printPDF() {
        const element = document.getElementById('print_report_area');
        element.style.display = 'block';
        const opt = {
            margin: 0.5,
            filename: `Purchase_Bills_Report.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2 },
            jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' }
        };
        window.html2pdf().set(opt).from(element).save().then(() => {
            element.style.display = 'none';
        });
    }

    renderCharts() {
        Object.values(this.chartInstances).forEach(chart => {
            if (chart) chart.destroy();
        });

        const chartsData = this.state.kpi_data.charts || {};
        const barOptions = { barPercentage: 0.4, categoryPercentage: 0.5 };

        if (this.chartRefs.chart_trend.el && chartsData.trend) {
            this.chartInstances.trend = new Chart(this.chartRefs.chart_trend.el, { type: 'line', data: chartsData.trend, options: { responsive: true, maintainAspectRatio: false, onClick: () => this.openAction('trend') }});
        }
        if (this.chartRefs.chart_status.el && chartsData.status) {
            this.chartInstances.status = new Chart(this.chartRefs.chart_status.el, { type: 'doughnut', data: chartsData.status, options: { responsive: true, maintainAspectRatio: false, onClick: (ev, elements) => {
                    if (elements.length > 0) {
                        const label = chartsData.status.labels[elements[0].index];
                        this.openAction('status', label === 'Paid' ? 'paid' : 'unpaid');
                    }
                }}
            });
        }
        if (this.chartRefs.chart_vendor.el && chartsData.vendor) {
            this.chartInstances.vendor = new Chart(this.chartRefs.chart_vendor.el, { type: 'bar', data: chartsData.vendor, options: { responsive: true, maintainAspectRatio: false, datasets: { bar: barOptions }, onClick: () => this.openAction('vendor') }});
        }
        if (this.chartRefs.chart_lead_time.el && chartsData.lead_time) {
            this.chartInstances.lead_time = new Chart(this.chartRefs.chart_lead_time.el, { type: 'bar', data: chartsData.lead_time, options: { responsive: true, maintainAspectRatio: false, datasets: { bar: barOptions }, onClick: () => this.openAction('lead_time') }});
        }
        if (this.chartRefs.chart_price_var.el && chartsData.price_var) {
            this.chartInstances.price_var = new Chart(this.chartRefs.chart_price_var.el, { type: 'bar', data: chartsData.price_var, options: { responsive: true, maintainAspectRatio: false, datasets: { bar: barOptions }, onClick: () => this.openAction('price_var') }});
        }
    }

    openAction(actionType, subType = null) {
        let domain = [['move_type', '=', 'in_invoice']];
        let name = "Bills Analysis";
        let res_model = 'account.move';
        let view_mode = 'list,form';
        let context = {};

        switch (actionType) {
            case 'all':
                name = "All Purchase Bills"; break;
            case 'lead_time':
                domain.push(['payment_state', '=', 'paid']); view_mode = 'list,pivot'; name = "Vendor Payment Lead Time Analysis"; break;
            case 'late_bills':
                const today = new Date().toISOString().split('T')[0];
                domain.push(['state', '=', 'posted'], ['payment_state', '!=', 'paid'], ['invoice_date_due', '<', today]); name = "Overdue Vendor Bills"; break;
            case 'dpo':
                domain.push(['payment_state', '=', 'paid']); view_mode = 'pivot'; name = "Paid Vendor Bills Analysis (DPO)"; context = {'search_default_group_by_partner_id': 1, 'pivot_measures': ['payment_lead_time']}; break;
            case 'status':
                if (subType === 'paid') domain.push(['payment_state', '=', 'paid']); else domain.push(['payment_state', '!=', 'paid']); name = "Payment Status Detail"; break;
            case 'price_var':
                domain.push(['invoice_line_ids.purchase_line_id', '!=', false]); name = "Price Variance (PO vs Bill)"; break;
            case 'wo_po':
                domain.push(['invoice_line_ids.purchase_line_id', '=', false]); name = "Vendor Bills Without PO"; break;
            case 'qty_variance_pivot':
                res_model = 'account.move.line'; domain = [['move_id.move_type', '=', 'in_invoice'], ['purchase_line_id', '!=', false]]; view_mode = 'pivot'; name = "Quantity Variance Analysis"; context = {'pivot_measures': ['qty_variance'], 'pivot_column_groupby': ['product_id'], 'pivot_row_groupby': ['partner_id']}; break;
            case 'upcoming':
                domain.push(['state', '=', 'posted'], ['payment_state', 'in', ['not_paid', 'partial']]); name = "Upcoming Payables"; break;
            case 'vendor': case 'trend':
                view_mode = 'graph,pivot,list'; break;
        }

        let dateFrom = this.filterRefs.date_from.el ? this.filterRefs.date_from.el.value : this.defaultDateFrom;
        let dateTo = this.filterRefs.date_to.el ? this.filterRefs.date_to.el.value : this.defaultDateTo;

        if (res_model === 'account.move') {
            domain.push(['invoice_date', '>=', dateFrom], ['invoice_date', '<=', dateTo]);
        } else if (res_model === 'account.move.line') {
            domain.push(['move_id.invoice_date', '>=', dateFrom], ['move_id.invoice_date', '<=', dateTo]);
        }

        if (this.state.filters.vendor_id !== "all") {
            if (res_model === 'account.move') domain.push(['partner_id', '=', parseInt(this.state.filters.vendor_id)]);
            else domain.push(['move_id.partner_id', '=', parseInt(this.state.filters.vendor_id)]);
        }

        if (this.state.filters.journal_id !== "all") {
            if (res_model === 'account.move') domain.push(['journal_id', '=', parseInt(this.state.filters.journal_id)]);
            else domain.push(['move_id.journal_id', '=', parseInt(this.state.filters.journal_id)]);
        }
        if (this.state.filters.category_id !== "all") {
            if (res_model === 'account.move') domain.push(['invoice_line_ids.product_id.categ_id', 'child_of', parseInt(this.state.filters.category_id)]);
            else domain.push(['product_id.categ_id', 'child_of', parseInt(this.state.filters.category_id)]);
        }
        if (this.state.filters.location_id !== "all") {
            if (res_model === 'account.move') domain.push(['invoice_line_ids.purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of', parseInt(this.state.filters.location_id)]);
            else domain.push(['purchase_line_id.order_id.picking_type_id.default_location_dest_id', 'child_of', parseInt(this.state.filters.location_id)]);
        }

        // دمج الدومين الخاص بشريط البحث (Native Search Bar)
        const searchDomain = (this.env.searchModel && this.env.searchModel.domain) ? this.env.searchModel.domain : [];
        if (searchDomain.length > 0) {
            domain = domain.concat(searchDomain);
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: res_model,
            view_mode: view_mode,
            views: view_mode.split(',').map(v => [false, v]),
            domain: domain,
            context: context,
            target: 'current'
        });
    }
}

PurchaseBillsDashboard.template = "purchase_bills_dashboard_template";
registry.category("actions").add("purchase_bills_dashboard_tag", PurchaseBillsDashboard);