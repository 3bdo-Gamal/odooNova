/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useRef, onMounted, useState } from "@odoo/owl";

// دالة تحميل Chart.js
function loadChartJs() {
    return new Promise((resolve, reject) => {
        if (typeof Chart !== 'undefined') { resolve(); return; }
        const script = document.createElement("script");
        script.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js";
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("Failed to load Chart.js"));
        document.head.appendChild(script);
    });
}

export class PurchaseBillsDashboard extends Component {
    setup() {
        this.orm = useService("orm"); // <--- التغيير هنا: استخدام ORM
        this.state = useState({ kpi_data: {}, loading: true, filter: 'this_year' });
        this.chartRefTrend = useRef("chart_trend");
        this.chartRefVendor = useRef("chart_vendor");

        onWillStart(async () => {
            try { await loadChartJs(); } catch (e) { console.error(e); }
            await this.fetchData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async fetchData() {
        this.state.loading = true;
        try {
            // التغيير الكبير هنا: مناداة الموديل بدلاً من الرابط
            const result = await this.orm.call(
                "wb.purchase.bills.dashboard", // اسم الموديل
                "get_kpi_data",                // اسم الدالة
                [],                            // args (فارغ)
                { date_filter: this.state.filter } // kwargs
            );

            this.state.kpi_data = result;
            this.state.loading = false;

            if (this.chartInstanceTrend) { this.renderCharts(); }
        } catch (error) {
            console.error("Error fetching data:", error);
            this.state.loading = false;
        }
    }

    async onChangeFilter(ev) {
        this.state.filter = ev.target.value;
        await this.fetchData();
        this.renderCharts();
    }

    renderCharts() {
        if (!this.state.kpi_data.charts || typeof Chart === 'undefined') return;

        // --- (نفس كود الرسم القديم بدون تغيير) ---
        // Spend Trend
        if (this.chartRefTrend.el) {
            const ctx = this.chartRefTrend.el.getContext('2d');
            if (this.chartInstanceTrend) this.chartInstanceTrend.destroy();
            this.chartInstanceTrend = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: this.state.kpi_data.charts.spend_trend.labels,
                    datasets: [{
                        label: 'Total Spend',
                        data: this.state.kpi_data.charts.spend_trend.data,
                        borderColor: '#2C3E50',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
        // Top Vendors
        if (this.chartRefVendor.el) {
            const ctx = this.chartRefVendor.el.getContext('2d');
            if (this.chartInstanceVendor) this.chartInstanceVendor.destroy();
            this.chartInstanceVendor = new Chart(ctx, {
                type: 'bar',
                indexAxis: 'y',
                data: {
                    labels: this.state.kpi_data.charts.top_vendors.labels,
                    datasets: [{
                        label: 'Amount',
                        data: this.state.kpi_data.charts.top_vendors.data,
                        backgroundColor: '#27AE60',
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
    }
}

PurchaseBillsDashboard.template = "purchase_bills_dashboard_template";
registry.category("actions").add("purchase_bills_dashboard_tag", PurchaseBillsDashboard);