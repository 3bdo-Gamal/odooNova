/** @odoo-module */
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class PurchaseBillsDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.chartRefs = {
            chart_trend: useRef("chart_trend"),
            chart_status: useRef("chart_status"),
            chart_vendor: useRef("chart_vendor"),
            chart_lead_time: useRef("chart_lead_time"),
            chart_price_var: useRef("chart_price_var")
        };

        // Refs لشريط البحث والتواريخ
        this.filterRefs = {
            date_from: useRef("date_from"),
            date_to: useRef("date_to"),
            vendor_search: useRef("vendor_search")
        };

        this.chartInstances = {};

          this.state = useState({
            kpi_data: {
                cards: { upcoming_payables: 0, avg_dpo: 0, late_bills_ratio: 0, wo_po_ratio: 0 },
                tables: { qty_variance_pivot: [] },
                charts: { trend: {}, status: {}, vendor: {}, lead_time: {}, price_var: {} }
            },
            active_filters: {
                state_posted: true, state_draft: false, pay_not_paid: false,
                pay_paid: false, is_overdue: false, has_po: false, no_po: false
            }
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");

            const today = new Date();
            const yyyy = today.getFullYear();
            let mm = today.getMonth() + 1;
            let dd = today.getDate();

            if (mm < 10) mm = '0' + mm;
            if (dd < 10) dd = '0' + dd;

            this.defaultDateFrom = `${yyyy}-01-01`; // أول يوم في السنة الحالية
            this.defaultDateTo = `${yyyy}-${mm}-${dd}`; // اليوم الحالي

            await this.fetchData(this.defaultDateFrom, this.defaultDateTo, "");
        });

        onMounted(() => {
            // تعبئة حقول التاريخ في الواجهة بالقيم الافتراضية عند التحميل
            if(this.filterRefs.date_from.el) this.filterRefs.date_from.el.value = this.defaultDateFrom;
            if(this.filterRefs.date_to.el) this.filterRefs.date_to.el.value = this.defaultDateTo;
            this.renderCharts();
        });
    }


    async toggleFilter(filterName) {
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
        await this.onApplyFilter();
    }

    async fetchData(dateFrom, dateTo, vendorName) {
        try {

            const data = await this.orm.call("wb.purchase.bills.dashboard", "get_dashboard_data", [], {
                date_from: dateFrom,
                date_to: dateTo,
                vendor_name: vendorName,
                active_filters: this.state.active_filters
            });

            if (data) {
                this.state.kpi_data = data;
            }
        } catch (error) {
            console.error("Error fetching bills dashboard data:", error);
        }
    }

    async onApplyFilter() {
        const dateFrom = this.filterRefs.date_from.el.value;
        const dateTo = this.filterRefs.date_to.el.value;
        const vendorName = this.filterRefs.vendor_search.el ? this.filterRefs.vendor_search.el.value : "";

        if (dateFrom && dateTo) {
            await this.fetchData(dateFrom, dateTo, vendorName);
            this.renderCharts();
        }
    }

    // تطبيق الفلتر تلقائياً عند الضغط على Enter في شريط البحث
    async onSearchKeyUp(ev) {
        if (ev.key === "Enter") {
            await this.onApplyFilter();
        }
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

        // قراءة الفلاتر الحالية (التاريخ والمورد) لتمريرها للشاشات الجديدة
        let dateFrom = this.filterRefs.date_from.el ? this.filterRefs.date_from.el.value : this.defaultDateFrom;
        let dateTo = this.filterRefs.date_to.el ? this.filterRefs.date_to.el.value : this.defaultDateTo;
        let vendorName = this.filterRefs.vendor_search.el ? this.filterRefs.vendor_search.el.value : "";

        // إضافة فلتر التاريخ للـ Domain
        if (res_model === 'account.move') {
            domain.push(['invoice_date', '>=', dateFrom], ['invoice_date', '<=', dateTo]);
        } else if (res_model === 'account.move.line') {
            domain.push(['move_id.invoice_date', '>=', dateFrom], ['move_id.invoice_date', '<=', dateTo]);
        }

        // إضافة فلتر المورد للـ Domain
        if (vendorName) {
            if (res_model === 'account.move.line') {
                domain.push(['move_id.partner_id.name', 'ilike', vendorName]);
            } else {
                domain.push(['partner_id.name', 'ilike', vendorName]);
            }
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