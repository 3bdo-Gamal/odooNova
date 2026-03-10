/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";

export class InventoryDashboardClient extends Component {
    static template = "InventoryDashboardClientTemplate";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.trendChartRef = useRef("trend_chart");
        this.abcChartRef = useRef("abc_chart");
        this.topProductChartRef = useRef("top_product_chart");
        this.locationChartRef = useRef("location_chart");

        this.state = useState({
            showSidebar: true,
            showExportModal: false,

            // Filters
            period: "30",
            date_from: "",
            date_to: "",
            warehouse_id: "all",
            product_id: "all",
            category_id: "all",
            location_id: "all",

            // Filter Options
            filter_warehouses: [],
            filter_products: [],
            filter_categories: [],
            filter_locations: [],

            // KPIs
            stock_on_hand: 0,
            stock_value: 0,
            stock_value_fmt: "0.00",
            cogs: 0,
            cogs_fmt: "0.00",
            received_value: 0,
            inventory_turnover: "0x",
            dio: "0 Days",
            low_stock_count: 0,
            dead_stock_count: 0,
            total_products: 0,

            // Chart Data
            trend_labels: [],
            trend_in: [],
            trend_out: [],
            abc_labels: [],
            abc_data: [],
            top_product_labels: [],
            top_product_data: [],
            location_labels: [],
            location_data: [],

            // Export Options
            export_group: "product",
            detailed_excel: false,
            meas_qty: true,
            meas_value: true,
            meas_cogs: true,
            meas_turnover: false,
            meas_category: false,
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await this.loadFilters();
            await this.fetchData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async loadFilters() {
        try {
            const data = await this.orm.call("wb.inventory.dashboard", "get_filter_options", []);
            if (data) {
                this.state.filter_warehouses = data.warehouses || [];
                this.state.filter_products = data.products || [];
                this.state.filter_categories = data.categories || [];
                this.state.filter_locations = data.locations || [];
            }
        } catch (e) {
            console.error("Error loading filters:", e);
        }
    }

    async fetchData() {
        const kwargs = {
            period: parseInt(this.state.period) || 30,
            date_from: this.state.date_from || false,
            date_to: this.state.date_to || false,
            warehouse_id: this.state.warehouse_id,
            product_id: this.state.product_id,
            category_id: this.state.category_id,
            location_id: this.state.location_id,
        };
        const data = await this.orm.call("wb.inventory.dashboard", "get_inventory_kpis", [], kwargs);
        if (data) {
            Object.assign(this.state, data);
            this.renderCharts();
        }
    }

    toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
    }

    async onChangeFilter() {
        await this.fetchData();
    }

    async onChangePeriod() {
        this.state.date_from = "";
        this.state.date_to = "";
        await this.fetchData();
    }

    async applyDateFilter() {
        if (this.state.date_from && this.state.date_to) {
            this.state.period = "0";
            await this.fetchData();
        }
    }

    async resetFilters() {
        this.state.period = "30";
        this.state.date_from = "";
        this.state.date_to = "";
        this.state.warehouse_id = "all";
        this.state.product_id = "all";
        this.state.category_id = "all";
        this.state.location_id = "all";
        await this.fetchData();
    }

    openView(res_model, domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: res_model,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openLowStock() {
        this.openView(
            "product.product",
            [["detailed_type", "=", "product"], ["qty_available", "<=", 0]],
            "Low Stock Products"
        );
    }

    openStockDetails() {
        this.openView(
            "stock.quant",
            [["location_id.usage", "=", "internal"]],
            "Stock On Hand"
        );
    }

    openProductList() {
        this.openView(
            "product.product",
            [["detailed_type", "=", "product"]],
            "All Products"
        );
    }

    openExportModal() {
        this.state.showExportModal = true;
    }

    closeExportModal() {
        this.state.showExportModal = false;
    }

    async downloadInventoryExcel() {
        this.state.showExportModal = false;
        const measures = [];
        if (this.state.meas_qty) measures.push("qty");
        if (this.state.meas_value) measures.push("value");
        if (this.state.meas_cogs) measures.push("cogs");
        if (this.state.meas_turnover) measures.push("turnover");
        if (this.state.meas_category) measures.push("category");

        if (measures.length === 0) {
            alert("Please select at least one measure.");
            return;
        }

        const kwargs = {
            period: parseInt(this.state.period) || 30,
            date_from: this.state.date_from || false,
            date_to: this.state.date_to || false,
            warehouse_id: this.state.warehouse_id,
            product_id: this.state.product_id,
            category_id: this.state.category_id,
            export_group: this.state.export_group,
            export_measures: measures,
            detailed_excel: this.state.detailed_excel,
        };

        const attachmentId = await this.orm.call(
            "wb.inventory.dashboard",
            "export_inventory_excel",
            [],
            kwargs
        );
        if (attachmentId) {
            window.location = `/web/content/${attachmentId}?download=true`;
        }
    }

    renderCharts() {
        this._renderTrendChart();
        this._renderAbcChart();
        this._renderTopProductChart();
        this._renderLocationChart();
    }

    _destroyChart(ref) {
        if (ref.el && ref.el.chartInstance) {
            ref.el.chartInstance.destroy();
            ref.el.chartInstance = null;
        }
    }

    _renderTrendChart() {
        const ref = this.trendChartRef;
        if (!ref.el) return;
        this._destroyChart(ref);
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: "line",
            data: {
                labels: this.state.trend_labels,
                datasets: [
                    {
                        label: "Stock In (Received)",
                        data: this.state.trend_in,
                        borderColor: "#10b981",
                        backgroundColor: "rgba(16,185,129,0.1)",
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2,
                    },
                    {
                        label: "Stock Out (Delivered)",
                        data: this.state.trend_out,
                        borderColor: "#ef4444",
                        backgroundColor: "rgba(239,68,68,0.1)",
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "top" } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    _renderAbcChart() {
        const ref = this.abcChartRef;
        if (!ref.el) return;
        this._destroyChart(ref);
        const colors = [
            "#4f46e5", "#10b981", "#f59e0b", "#ef4444", "#06b6d4",
            "#a855f7", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
        ];
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: "doughnut",
            data: {
                labels: this.state.abc_labels,
                datasets: [
                    {
                        data: this.state.abc_data,
                        backgroundColor: colors.slice(0, this.state.abc_labels.length),
                        borderWidth: 2,
                        hoverOffset: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
            },
        });
    }

    _renderTopProductChart() {
        const ref = this.topProductChartRef;
        if (!ref.el) return;
        this._destroyChart(ref);
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: "bar",
            data: {
                labels: this.state.top_product_labels,
                datasets: [
                    {
                        label: "Quantity Out",
                        data: this.state.top_product_data,
                        backgroundColor: "#4f46e5",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true } },
                onClick: (e, activeEls) => {
                    if (activeEls.length > 0) {
                        const label = this.state.top_product_labels[activeEls[0].index];
                        this.openView(
                            "stock.move",
                            [
                                ["state", "=", "done"],
                                ["location_dest_id.usage", "=", "customer"],
                                ["product_id.display_name", "=", label],
                            ],
                            `Moves: ${label}`
                        );
                    }
                },
                onHover: (e, activeEls) => {
                    e.native.target.style.cursor = activeEls.length > 0 ? "pointer" : "default";
                },
            },
        });
    }

    _renderLocationChart() {
        const ref = this.locationChartRef;
        if (!ref.el) return;
        this._destroyChart(ref);
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: "bar",
            data: {
                labels: this.state.location_labels,
                datasets: [
                    {
                        label: "Qty On Hand",
                        data: this.state.location_data,
                        backgroundColor: "#06b6d4",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } },
                onClick: (e, activeEls) => {
                    if (activeEls.length > 0) {
                        const label = this.state.location_labels[activeEls[0].index];
                        this.openView(
                            "stock.quant",
                            [
                                ["location_id.usage", "=", "internal"],
                                ["location_id.complete_name", "=", label],
                            ],
                            `Stock at: ${label}`
                        );
                    }
                },
                onHover: (e, activeEls) => {
                    e.native.target.style.cursor = activeEls.length > 0 ? "pointer" : "default";
                },
            },
        });
    }
}

registry.category("actions").add("inventory_dashboard_client_tag", InventoryDashboardClient);