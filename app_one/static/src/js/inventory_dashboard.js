/** @odoo-module **/
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
// FIX: Added onWillUnmount to prevent chart memory leaks on view destroy
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";

export class InventoryDashboardClient extends Component {
    static template = "InventoryDashboardClientTemplate";

    get currentField() {
        if (!this.state.model_fields || this.state.model_fields.length === 0) return {};
        return this.state.model_fields.find(f => f.name === this.state.cf_field) || {};
    }

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.trendChartRef      = useRef("trend_chart");
        this.abcChartRef        = useRef("abc_chart");
        this.topProductChartRef = useRef("top_product_chart");
        this.locationChartRef   = useRef("location_chart");
        // FIX: Removed dead valueChartRef — no canvas, no render method, causes confusion

        // ── Load saved state from localStorage ──────────────────────────
        const savedState    = JSON.parse(localStorage.getItem('wb_inventory_dashboard_state_v2')) || {};
        const savedFavorites = JSON.parse(localStorage.getItem('inventory_dashboard_favorites')) || [];
        const defaultFav    = savedFavorites.find(f => f.is_default === true);

        this.state = useState({
            // ── UI ─────────────────────────────────────────────────────
            showSidebar:     true,
            showExportModal: false,
            showPdfModal:    false,
            isLoading:       false,

            // ── Period / date filters ──────────────────────────────────
            period:       savedState.period    || "30",
            date_from:    savedState.date_from || "",
            date_to:      savedState.date_to   || "",

            // ── Dimension filters ──────────────────────────────────────
            warehouse_id: savedState.warehouse_id || "all",
            product_id:   savedState.product_id   || "all",
            category_id:  savedState.category_id  || "all",
            location_id:  savedState.location_id  || "all",

            // ── Top-N chart controls (mirror sales dashboard dropdowns) ─
            top_products:   String(savedState.top_products  || "10"),
            top_locations:  String(savedState.top_locations || "10"),
            top_categories: String(savedState.top_categories || "10"),

            // ── Filter option lists ────────────────────────────────────
            filter_warehouses: [],
            filter_products:   [],
            filter_categories: [],
            filter_locations:  [],
            model_fields:      [],

            // ── Quick-filter toggles ───────────────────────────────────
            active_filters: defaultFav
                ? { ...defaultFav.active_filters }
                : (savedState.active_filters || {
                    low_stock:  false,
                    dead_stock: false,
                    no_reorder: false,
                }),

            // ── Search / custom domain ─────────────────────────────────
            search_query: defaultFav
                ? defaultFav.search_query
                : (savedState.search_query || ''),

            custom_domain:           defaultFav ? [...defaultFav.custom_domain] : (savedState.custom_domain || []),
            show_custom_filter_menu: false,
            cf_field:    '',
            cf_operator: '=',
            cf_value:    '',

            // ── Group by ───────────────────────────────────────────────
            group_by_list:         defaultFav ? [...defaultFav.group_by_list] : (savedState.group_by_list || []),
            show_custom_group_menu: false,
            cg_field: '',

            // ── Favorites ─────────────────────────────────────────────
            active_favorite_name: defaultFav ? defaultFav.name : null,
            saved_favorites:      savedFavorites,
            show_save_menu:       false,
            favorite_name:        'Inventory Analytics',
            is_default_fav:       false,
            is_shared_fav:        false,

            // ── KPIs ───────────────────────────────────────────────────
            stock_on_hand:      0,
            stock_value:        0,
            stock_value_fmt:    "0.00",
            cogs:               0,
            cogs_fmt:           "0.00",
            received_value:     0,
            received_value_fmt: "0.00",
            inventory_turnover: "0x",
            dio:                "0 Days",
            low_stock_count:    0,
            dead_stock_count:   0,
            total_products:     0,

            // ── Chart data ─────────────────────────────────────────────
            trend_labels:       [],
            trend_in:           [],
            trend_out:          [],
            // FIX: Keys now match backend response keys exactly
            category_value_labels: [],
            category_value_data:   [],
            top_product_labels: [],
            top_product_data:   [],
            location_labels:    [],
            location_data:      [],

            // ── Export options ─────────────────────────────────────────
            export_group:   "product",
            detailed_excel: false,
            meas_qty:       true,
            meas_value:     true,
            meas_cogs:      true,
            meas_turnover:  false,
            meas_category:  false,

            // ── PDF options ────────────────────────────────────────────
            pdf_stock:     true,
            pdf_value:     true,
            pdf_cogs:      true,
            pdf_turnover:  true,
            pdf_low_stock: true,
            pdf_dead:      true,
        });

        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js");
            await this.loadFilters();
            await this.fetchData(false);
        });

        onMounted(() => {
            this.renderCharts();
        });

        // FIX: Properly destroy all chart instances on component teardown to prevent memory leaks
        onWillUnmount(() => {
            this._destroyChart(this.trendChartRef);
            this._destroyChart(this.abcChartRef);
            this._destroyChart(this.topProductChartRef);
            this._destroyChart(this.locationChartRef);
        });
    }

    // ── Filter loader ───────────────────────────────────────────────────

    async loadFilters() {
        try {
            const data = await this.orm.call("wb.inventory.dashboard", "get_filter_options", []);
            if (data) {
                this.state.filter_warehouses = data.warehouses || [];
                this.state.filter_products   = data.products   || [];
                this.state.filter_categories = data.categories || [];
                this.state.filter_locations  = data.locations  || [];

                this.state.model_fields = [
                    { name: 'product_id',        string: 'Product',          type: 'many2one' },
                    { name: 'categ_id',          string: 'Category',         type: 'many2one' },
                    { name: 'location_id',       string: 'Location',         type: 'many2one' },
                    { name: 'quantity',          string: 'Quantity on Hand', type: 'float'    },
                    { name: 'product_id.active', string: 'Active',           type: 'boolean'  },
                ];
                if (this.state.model_fields.length > 0) {
                    this.state.cf_field = this.state.model_fields[0].name;
                    this.state.cg_field = this.state.model_fields[0].name;
                }
            }
        } catch (e) {
            console.error("Error loading filters:", e);
        }
    }

    // ── Data fetch ──────────────────────────────────────────────────────

    async fetchData(renderAfter = true) {
        this.state.isLoading = true;
        try {
            const kwargs = {
                period:         parseInt(this.state.period) || 30,
                date_from:      this.state.date_from || false,
                date_to:        this.state.date_to   || false,
                warehouse_id:   this.state.warehouse_id,
                product_id:     this.state.product_id,
                category_id:    this.state.category_id,
                location_id:    this.state.location_id,
                // FIX: Pass top-N params so backend respects the dropdown values
                top_products:   parseInt(this.state.top_products)   || 10,
                top_locations:  parseInt(this.state.top_locations)  || 10,
                top_categories: parseInt(this.state.top_categories) || 10,
            };
            const data = await this.orm.call(
                "wb.inventory.dashboard", "get_inventory_kpis", [], kwargs
            );
            if (data) {
                Object.assign(this.state, data);
                if (!data.received_value_fmt) {
                    this.state.received_value_fmt =
                        (data.received_value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                }
                this._persistState();
                if (renderAfter) this.renderCharts();
            }
        } catch (e) {
            console.error("Error fetching inventory KPIs:", e);
        } finally {
            this.state.isLoading = false;
        }
    }

    _persistState() {
        const toSave = {
            period: this.state.period, date_from: this.state.date_from, date_to: this.state.date_to,
            warehouse_id: this.state.warehouse_id, product_id: this.state.product_id,
            category_id: this.state.category_id, location_id: this.state.location_id,
            top_products: this.state.top_products,
            top_locations: this.state.top_locations,
            top_categories: this.state.top_categories,
            search_query: this.state.search_query, active_filters: { ...this.state.active_filters },
            custom_domain: [...this.state.custom_domain], group_by_list: [...this.state.group_by_list],
        };
        localStorage.setItem('wb_inventory_dashboard_state_v2', JSON.stringify(toSave));
    }

    // ── Period / filter actions ─────────────────────────────────────────

    toggleSidebar() { this.state.showSidebar = !this.state.showSidebar; }

    async onChangePeriod() {
        this.state.date_from = "";
        this.state.date_to   = "";
        await this.fetchData();
    }

    async applyDateFilter() {
        if (this.state.date_from && this.state.date_to) {
            this.state.period = "0";
            await this.fetchData();
        }
    }

    async onChangeFilter() { await this.fetchData(); }

    async resetFilters() {
        this.state.period            = "30";
        this.state.date_from         = "";
        this.state.date_to           = "";
        this.state.warehouse_id      = "all";
        this.state.product_id        = "all";
        this.state.category_id       = "all";
        this.state.location_id       = "all";
        this.state.top_products      = "10";
        this.state.top_locations     = "10";
        this.state.top_categories    = "10";
        this.state.search_query      = "";
        this.state.active_filters    = { low_stock: false, dead_stock: false, no_reorder: false };
        this.state.custom_domain     = [];
        this.state.group_by_list     = [];
        this.state.active_favorite_name = null;
        await this.fetchData();
    }

    // ── Search ──────────────────────────────────────────────────────────

    async onSearchKeyUp(ev) {
        if (ev.key === 'Enter' && ev.target.value.trim() !== '') {
            this.state.active_favorite_name = null;
            this.state.search_query = ev.target.value;
            ev.target.value = '';
            await this.fetchData();
        }
    }
    async clearSearchQuery() { this.state.active_favorite_name = null; this.state.search_query = ''; await this.fetchData(); }

    // ── Quick filters ───────────────────────────────────────────────────

    async toggleFilter(filterName) {
        this.state.active_favorite_name = null;
        this.state.active_filters[filterName] = !this.state.active_filters[filterName];
        await this.fetchData();
    }

    // ── Custom filter ───────────────────────────────────────────────────

    toggleCustomFilterMenu(ev) { ev.stopPropagation(); this.state.show_custom_filter_menu = !this.state.show_custom_filter_menu; }

    async addCustomFilter(ev) {
        ev.stopPropagation();
        if (this.state.cf_field && this.state.cf_value !== '') {
            const fieldObj = this.state.model_fields.find(f => f.name === this.state.cf_field);
            this.state.custom_domain.push({
                field: this.state.cf_field,
                label: fieldObj ? fieldObj.string : this.state.cf_field,
                operator: this.state.cf_operator,
                value: this.state.cf_value,
                type: fieldObj ? fieldObj.type : 'char',
            });
            this.state.active_favorite_name = null;
            this.state.cf_value = '';
            this.state.show_custom_filter_menu = false;
            await this.fetchData();
        }
    }

    async removeCustomFilter(index) {
        this.state.active_favorite_name = null;
        this.state.custom_domain.splice(index, 1);
        await this.fetchData();
    }

    // ── Group by ────────────────────────────────────────────────────────

    toggleCustomGroupMenu(ev) { ev.stopPropagation(); this.state.show_custom_group_menu = !this.state.show_custom_group_menu; }

    async addCustomGroupBy(ev) {
        ev.stopPropagation();
        if (this.state.cg_field && !this.state.group_by_list.includes(this.state.cg_field)) {
            this.state.active_favorite_name = null;
            this.state.group_by_list.push(this.state.cg_field);
            this.state.show_custom_group_menu = false;
            await this.fetchData();
        }
    }

    async toggleGroupBy(groupName) {
        this.state.active_favorite_name = null;
        if (this.state.group_by_list.includes(groupName)) {
            this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        } else {
            this.state.group_by_list.push(groupName);
        }
        await this.fetchData();
    }

    async removeGroupBy(groupName) {
        this.state.active_favorite_name = null;
        this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        await this.fetchData();
    }

    // ── Favorites ────────────────────────────────────────────────────────

    toggleSaveMenu(ev) { ev.stopPropagation(); this.state.show_save_menu = !this.state.show_save_menu; }
    onDefaultCheckboxChange() { if (this.state.is_default_fav) this.state.is_shared_fav = false; }
    onSharedCheckboxChange()  { if (this.state.is_shared_fav)  this.state.is_default_fav = false; }

    saveFavoriteUI(ev) {
        ev.stopPropagation();
        if (this.state.favorite_name.trim()) {
            if (this.state.is_default_fav) this.state.saved_favorites.forEach(f => f.is_default = false);
            const newFav = {
                id: Date.now(),
                name: this.state.favorite_name,
                search_query: this.state.search_query,
                active_filters: { ...this.state.active_filters },
                custom_domain: [...this.state.custom_domain],
                group_by_list: [...this.state.group_by_list],
                is_default: this.state.is_default_fav,
                is_shared: this.state.is_shared_fav,
            };
            this.state.saved_favorites.push(newFav);
            localStorage.setItem('inventory_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
            this.state.show_save_menu   = false;
            this.state.favorite_name    = 'Inventory Analytics';
            this.state.is_default_fav   = false;
            this.state.is_shared_fav    = false;
        }
    }

    loadFavorite(fav) {
        this.state.search_query         = fav.search_query;
        this.state.active_filters       = { ...fav.active_filters };
        this.state.custom_domain        = [...fav.custom_domain];
        this.state.group_by_list        = [...fav.group_by_list];
        this.state.active_favorite_name = fav.name;
        this.fetchData();
    }

    clearFavorite() {
        this.state.active_favorite_name = null;
        this.state.search_query         = '';
        this.state.active_filters       = { low_stock: false, dead_stock: false, no_reorder: false };
        this.state.custom_domain        = [];
        this.state.group_by_list        = [];
        this.fetchData();
    }

    deleteFavorite(id) {
        this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== id);
        localStorage.setItem('inventory_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
    }

    // ── Navigation helpers ──────────────────────────────────────────────

    openView(res_model, domain, name) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name,
            res_model,
            views:     [[false, "list"], [false, "form"]],
            domain,
            target:    "current",
        });
    }

    openLowStock()    { this.openView("stock.warehouse.orderpoint", [], "Reorder Rules (Low Stock)"); }
    openStockDetails(){ this.openView("stock.quant", [["location_id.usage", "=", "internal"]], "Stock On Hand"); }
    openProductList() { this.openView("product.product", [["detailed_type", "=", "product"]], "All Products"); }
    openDeadStock()   { this.openView("stock.quant", [["location_id.usage", "=", "internal"]], "Dead Stock (No Movement)"); }

    // ── Export modal ─────────────────────────────────────────────────────

    openExportModal()  { this.state.showExportModal = true; }
    closeExportModal() { this.state.showExportModal = false; }
    openPdfModal()     { this.state.showPdfModal = true; }
    closePdfModal()    { this.state.showPdfModal = false; }

    async downloadInventoryExcel() {
        this.state.showExportModal = false;
        const measures = [];
        if (this.state.meas_qty)      measures.push("qty");
        if (this.state.meas_value)    measures.push("value");
        if (this.state.meas_cogs)     measures.push("cogs");
        if (this.state.meas_turnover) measures.push("turnover");
        if (this.state.meas_category) measures.push("category");

        if (measures.length === 0) { alert("Please select at least one measure."); return; }

        const kwargs = {
            period:          parseInt(this.state.period) || 30,
            date_from:       this.state.date_from || false,
            date_to:         this.state.date_to   || false,
            warehouse_id:    this.state.warehouse_id,
            product_id:      this.state.product_id,
            category_id:     this.state.category_id,
            export_group:    this.state.export_group,
            export_measures: measures,
            detailed_excel:  this.state.detailed_excel,
        };
        const attachmentId = await this.orm.call("wb.inventory.dashboard", "export_inventory_excel", [], kwargs);
        if (attachmentId) window.location = `/web/content/${attachmentId}?download=true`;
    }

    printCleanPDF() {
        this.state.showPdfModal = false;
        const area = document.getElementById('inv_print_report_area');
        if (!area || !window.html2pdf) return;
        area.style.display = 'block';
        window.html2pdf().set({
            margin: 10,
            filename: 'Inventory_Report.pdf',
            html2canvas: { scale: 2 },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
        }).from(area).save().then(() => { area.style.display = 'none'; });
    }

    // ── Chart rendering ─────────────────────────────────────────────────

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
                        fill: true, tension: 0.4, borderWidth: 2,
                    },
                    {
                        label: "Stock Out (Delivered)",
                        data: this.state.trend_out,
                        borderColor: "#ef4444",
                        backgroundColor: "rgba(239,68,68,0.1)",
                        fill: true, tension: 0.4, borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { position: "top" } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    _renderAbcChart() {
        const ref = this.abcChartRef;
        if (!ref.el) return;
        this._destroyChart(ref);

        // FIX: Use correct state keys that match the backend response
        const labels = this.state.category_value_labels || [];
        const data   = this.state.category_value_data   || [];

        if (!labels || labels.length === 0) {
            const ctx = ref.el.getContext("2d");
            ctx.clearRect(0, 0, ref.el.width, ref.el.height);
            ctx.font = "14px sans-serif"; ctx.fillStyle = "#94a3b8";
            ctx.textAlign = "center"; ctx.textBaseline = "middle";
            ctx.fillText("No category stock value data", ref.el.width / 2, ref.el.height / 2);
            return;
        }
        const colors = ["#4f46e5","#10b981","#f59e0b","#ef4444","#06b6d4","#a855f7","#ec4899","#14b8a6","#f97316","#6366f1"];
        ref.el.chartInstance = new window.Chart(ref.el, {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{ data: data, backgroundColor: colors.slice(0, labels.length), borderWidth: 2, hoverOffset: 6 }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { position: "right", labels: { boxWidth: 12 } } },
                onClick: (e, activeEls) => {
                    if (activeEls.length > 0) {
                        const label = labels[activeEls[0].index];
                        this.openView("product.product", [["categ_id.name", "=", label], ["detailed_type", "=", "product"]], `Products in: ${label}`);
                    }
                },
                onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? "pointer" : "default"; },
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
                datasets: [{ label: "Quantity Out", data: this.state.top_product_data, backgroundColor: "#4f46e5", borderRadius: 6 }],
            },
            options: {
                indexAxis: "y", responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true } },
                onClick: (e, activeEls) => {
                    if (activeEls.length > 0) {
                        const label = this.state.top_product_labels[activeEls[0].index];
                        this.openView("stock.move", [["state","=","done"],["location_dest_id.usage","=","customer"],["product_id.display_name","=",label]], `Moves: ${label}`);
                    }
                },
                onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? "pointer" : "default"; },
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
                datasets: [{ label: "Qty On Hand", data: this.state.location_data, backgroundColor: "#06b6d4", borderRadius: 6 }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } },
                onClick: (e, activeEls) => {
                    if (activeEls.length > 0) {
                        const label = this.state.location_labels[activeEls[0].index];
                        this.openView("stock.quant", [["location_id.usage","=","internal"],["location_id.complete_name","=",label]], `Stock at: ${label}`);
                    }
                },
                onHover: (e, activeEls) => { e.native.target.style.cursor = activeEls.length > 0 ? "pointer" : "default"; },
            },
        });
    }
}

registry.category("actions").add("inventory_dashboard_client_tag", InventoryDashboardClient);