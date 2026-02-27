/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
const { Component, onWillStart, onMounted, useState } = owl;

export class InventoryDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            kpis: {},
            filters: {
                product_id: "",
                warehouse_id: "",
                date_from: "",
                date_to: ""
            }
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.loadData();
        });

        onMounted(() => { this.renderCharts(); });
    }

    async loadData() {
        this.state.kpis = await this.orm.call("wb.inventory.dashboard", "get_inventory_kpis", [this.state.filters]);
    }

    // الدالة المسؤولة عن فتح القوائم عند الضغط (Drill-down)
    openView(res_model, domain, name) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: res_model,
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }

    async onFilterChange(ev, type) {
        this.state.filters[type] = ev.target.value;
        await this.loadData();
        this.renderCharts();
    }

    async resetFilters() {
        this.state.filters = { product_id: "", warehouse_id: "", date_from: "", date_to: "" };
        await this.loadData();
        this.renderCharts();
    }

    renderCharts() {
        const ctx = document.getElementById('abcChart');
        if (!ctx || !this.state.kpis.abc_data) return;
        const existingChart = Chart.getChart(ctx);
        if (existingChart) existingChart.destroy();

        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: this.state.kpis.abc_data.labels,
                datasets: [{
                    data: this.state.kpis.abc_data.data,
                    backgroundColor: ['#5C6BC0', '#66BB6A', '#FFA726', '#EF5350'],
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }
}

InventoryDashboard.template = "app_one.InventoryDashboard";
registry.category("actions").add("inventory_dashboard_client_tag", InventoryDashboard);