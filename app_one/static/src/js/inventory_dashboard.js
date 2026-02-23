/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

const { Component, onWillStart, onMounted, useState, onWillUnmount } = owl;

export class InventoryDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({
            kpis: {},
        });

        // تعريف متغير للتشارت عشان نعرف نمسحه لما نخرج من الصفحة
        this.abcChart = null;

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.loadData();
        });

        onMounted(() => {
            // ركزي هنا: قللنا الـ Timeout شوية وخليناه يرسم بدقة
            setTimeout(() => {
                this.renderCharts();
            }, 300);
        });

        // تنظيف الذاكرة لما تقفلي الداشبورد
        onWillUnmount(() => {
            if (this.abcChart) {
                this.abcChart.destroy();
            }
        });
    }

    async loadData() {
        this.state.kpis = await this.orm.call("wb.inventory.dashboard", "get_inventory_kpis", []);
    }

    renderCharts() {
        const ctx = document.getElementById('abcChart');
        if (!ctx) return;

        // لو فيه تشارت قديم موجود فعلاً اتمسح
        const existingChart = Chart.getChart(ctx);
        if (existingChart) {
            existingChart.destroy();
        }

        const data = this.state.kpis.abc_data || {labels: [], data: []};

        // حفظ الـ Chart في المتغير بتاع الكومبوننت
        this.abcChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.data,
                    backgroundColor: ['#5C6BC0', '#66BB6A', '#FFA726'],
                    borderWidth: 2,
                    borderColor: '#ffffff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false, // ده اللي بيخليه يلتزم بالـ Height اللي حطيناه في الـ XML
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            boxWidth: 12,
                            padding: 20
                        }
                    }
                }
            }
        });
    }
}

InventoryDashboard.template = "app_one.InventoryDashboard";
registry.category("actions").add("inventory_dashboard_client_tag", InventoryDashboard);