/* @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { SearchModel } from "@web/search/search_model";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSubEnv } from "@odoo/owl";

const { Component, onWillStart, onMounted, useState, useRef } = owl;

export class PurchaseDashboard extends Component {
    static components = {SearchBar};

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.viewService = useService("view");
        this.userService = useService("user");

        this.searchModel = new SearchModel(this.env, {
            resModel: "purchase.order",
            user: this.userService,
            orm: this.orm,
            view: this.viewService,
        });

        useSubEnv({
            searchModel: this.searchModel,
        });

const savedPeriod = sessionStorage.getItem("po_dashboard_period") || "30";
        this.orderRef = useRef("state_chart_container");
        this.delayRef = useRef("delays_chart_container");
        this.vendorChartRef = useRef("vendorChartCanvas");

        const today = new Date();
        const lastWeek = new Date(today);
        lastWeek.setDate(lastWeek.getDate() - 7);
        const formatDate = (date) => date.toISOString().split('T')[0];
        const todayStr = formatDate(today);
        const lastWeekStr = formatDate(lastWeek);
        const savedStartDate = sessionStorage.getItem("po_dashboard_start") || lastWeekStr;
        const savedEndDate = sessionStorage.getItem("po_dashboard_end") || todayStr;
        const savedSidebar = sessionStorage.getItem("po_dashboard_sidebar") !== "false";
         const savedFavorites = JSON.parse(localStorage.getItem('po_dashboard_favorites')) || [];
        const defaultFav = savedFavorites.find(f => f.is_default === true);
           const savedState = JSON.parse(localStorage.getItem('wb_po_dashboard_state_v2')) || {};

        this.state = useState({
            model_fields: [], //fields that be searched
            custom_domain: [], //active filters now
            search_query: "",
            cf_field: "name",
            cf_operator: "=",
            cf_value: "",
              group_by_list: defaultFav ? [...defaultFav.group_by_list] : (savedState.group_by_list || []),
             show_custom_filter_menu: false,
            cg_field: '',
              active_favorite_name: defaultFav ? defaultFav.name : null,
            saved_favorites: savedFavorites,
            show_save_menu: false,
            favorite_name: 'po Analytics',
             is_default_fav: false,
            is_shared_fav: false,
    //         purchase_standard_filters: [
    //     { id: "rfq", string: "Requests for Quotation", domain: "[('state', 'in', ('draft', 'sent'))]" },
    //     { id: "orders", string: "Purchase Orders", domain: "[('state', 'in', ('purchase', 'done'))]" },
    //     { id: "my_orders", string: "My Orders", domain: "[('user_id', '=', uid)]" },
    // ],

            stats: {
                filter_options: {
                vendors: [],
                categories: [],
                locations: []
},
filters: {
    vendor_id: "all",
    category_id: "all",
    location_id: "all"
},
active_filters: {
    state_posted: false,
    state_draft: false,
    pay_paid: false,
    my_purchases: false,
    rfqs: false,
    purchase_orders: false,
    to_receive: false
},

                employeeData: [],
                avg_savings: 0,
                avg_lead_time: 0.0,
                emergency_count: 0,
                total_delay_days: 0,
                max_risk: 0.0,
                automation_rate:0.0,
                period: savedPeriod,
                vendor_spending_labels: [],
                vendor_spending_values: [],
                vendor_name: [],
                order_state_data: [],
                late_vendor_names: [],
                late_vendor_values: [],

                start_date: savedStartDate,
                end_date: savedEndDate,
                today_date: todayStr,

                show_avg_savings: true,
                show_avg_lead_time: true,
                show_emergency_count: true,
                show_total_delay_days: true,
                show_max_risk: true,
                show_automation_rate:true,

            },
   top_vendor_name: "",
             showSidebar: savedSidebar,
        });

        this.last_valid_start = savedStartDate;
        this.last_valid_end = savedEndDate;


        onWillStart(async () => {

            const options = await this.orm.call("wb.po.dashboard", "get_filter_options", []);
            this.state.model_fields = options.model_fields;


            await loadJS("/web/static/lib/Chart/Chart.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.3.0/exceljs.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js");
        });

        onMounted(async () => {
           await this.downloaddata();

        });
    }
// ////////////////////////////////////////////////////////////////////////
    //  (Standard Filters)
applyStandardFilter(filter) {

    this.state.search_query = filter.string;
    this.downloaddata(filter.domain);
}
saveToFavorites() {
    const newFavName = prompt("Enter a name for this search:");
    if (newFavName) {
        this.state.favorites.push({
            id: Date.now(),
            name: newFavName
        });
    }
}

    //add new filter
    addCustomFilter() {
        if (!this.state.cf_value || !this.state.cf_field) return;
        const fieldObj = this.state.model_fields.find(f => f.name === this.state.cf_field)
        if (fieldObj) {
            this.state.custom_domain.push({
                field: this.state.cf_field,
                field_string: fieldObj.string,
                operator: this.state.cf_operator,
                value: this.state.cf_value,
                type: fieldObj.type,
            });
            this.state.cf_value = "";
            this.downloaddata();
        }
    }

    //delete filter
    removeFilter(index){
        this.state.custom_domain.splice(index,1)
        this.downloaddata()
    }
      async clearSearchQuery() { this.state.active_favorite_name = null; this.state.search_query = ''; await this.downloaddata(); }

     async removeCustomFilter(index) {
        this.state.active_favorite_name = null;
        this.state.custom_domain.splice(index, 1);
        await this.downloaddata();
    }

       toggleCustomGroupMenu(ev) { ev.stopPropagation(); this.state.show_custom_group_menu = !this.state.show_custom_group_menu; }
       toggleSaveMenu(ev) { ev.stopPropagation(); this.state.show_save_menu = !this.state.show_save_menu; }
        onDefaultCheckboxChange() { if (this.state.is_default_fav) this.state.is_shared_fav = false; }
     onSharedCheckboxChange() { if (this.state.is_shared_fav) this.state.is_default_fav = false; }

      loadFavorite(fav) {
        this.state.search_query = fav.search_query;
        this.state.stats.active_filters = { ...fav.active_filters };
        this.state.custom_domain = [...fav.custom_domain];
        this.state.group_by_list = [...fav.group_by_list];
        this.state.active_favorite_name = fav.name;
        this.downloaddata();
    }

    saveFavoriteUI(ev) {
        ev.stopPropagation();
        if (this.state.favorite_name.trim()) {
            if (this.state.is_default_fav) this.state.saved_favorites.forEach(f => f.is_default = false);
            const newFav = {
                id: Date.now(), name: this.state.favorite_name, search_query: this.state.search_query,
                active_filters: { ...this.state.active_filters }, custom_domain: [...this.state.custom_domain],
                group_by_list: [...this.state.group_by_list], is_default: this.state.is_default_fav, is_shared: this.state.is_shared_fav
            };
            this.state.saved_favorites.push(newFav);
            localStorage.setItem('sales_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
            this.state.show_save_menu = false; this.state.favorite_name = 'po Analytics';
            this.state.is_default_fav = false; this.state.is_shared_fav = false;
        }
    }
     async addCustomGroupBy(ev) {
        ev.stopPropagation();
        if(this.state.cg_field && !this.state.group_by_list.includes(this.state.cg_field)) {
            this.state.active_favorite_name = null;
            this.state.group_by_list.push(this.state.cg_field);
            this.state.show_custom_group_menu = false;
            await this.downloaddata();
        }
    }

    async clearFavorite() {
        this.state.active_favorite_name = null;
        this.state.search_query = '';
       this.state.active_filters.my_purchases = false;
    this.state.active_filters.rfqs = false;
    this.state.active_filters.purchase_orders = false;
    this.state.active_filters.to_receive = false;
        this.state.custom_domain = [];
        this.state.group_by_list = [];
        await this.downloaddata();
    }

     deleteFavorite(favId) {
        this.state.saved_favorites = this.state.saved_favorites.filter(f => f.id !== favId);
        localStorage.setItem('po_dashboard_favorites', JSON.stringify(this.state.saved_favorites));
    }

     async removeGroupBy(groupName) {
        this.state.active_favorite_name = null;
        this.state.group_by_list = this.state.group_by_list.filter(g => g !== groupName);
        await this.downloaddata();
    }
//     //////////////////////////////////////////////////////////////
toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
        sessionStorage.setItem("po_dashboard_sidebar", this.state.showSidebar);
    }

onSearchKeyUp(ev) {
        this.state.search_query = ev.target.value;
        if (ev.key === "Enter") {
            this.downloaddata();
        }
    }
//     //////////////////////////////////////////////////////////////

    openKpiAction(actionType,vendorName = null) {
      let domain = [];
      let name = "Purchase Analysis";
    let res_model = 'purchase.order';
    let view_mode = 'tree,form';
    let context = {};
    let target_view_name = '';

    const startDate = this.state.stats.start_date || false
    const endDate = this.state.stats.end_date || false

        const offset = new Date().getTimezoneOffset() * 60000;
    const localTodayStr = (new Date(Date.now() - offset)).toISOString().split('T')[0];
        switch (actionType||vendorName) {

          case 'savings':

            view_mode = 'list,pivot,graph';
            name = "Price Variance & Savings Analysis";
            domain.push(
                ['requisition_id', '!=', false],
                ['price_variance', '>', 0]
            );

            context = {
                'group_by': 'partner_id',
            };
            break;

         case 'emergency':

            view_mode = 'list,form';
            name = "Urgent Procurement Requests";
            domain.push(['is_emergency', '=', true]);
            break;

           case 'lead_time':
            view_mode = 'list,pivot';
            name = "Purchase Order Lead Time Analysis";
            context = {
                'pivot_row_groupby': ['partner_id'],
            };
            break;

case 'delay':
    view_mode = 'list,pivot,form';

    domain.push(
        ['state', 'in', ['purchase', 'done']],
        ['date_planned', '!=', false],
        ['date_planned', '<', localTodayStr] // مقارنة الحقل بمتغير تاريخ اليوم النصي المجهز فوق
    );
    name = "Vendor Delivery Delays";
    context = {
        'group_by': 'partner_id'
    };
    break;

case 'vendor_max_risk':
            view_mode = 'list,form';
            name = `Orders for Top Vendor: ${vendorName || 'Max Spend'}`;
            domain.push(['state', 'in', ['purchase', 'done']]);
            if (vendorName) {
                domain.push(['partner_id.name', 'ilike', vendorName]);
            }
            break;

        case 'automation_rate':
            view_mode = 'list,pivot,form';
            name = "PO Automation & Creation Source";
            domain.push(['state', 'in', ['purchase', 'done']]);
            context = {
                'group_by': 'origin'
            };
            break;
    }

if (actionType !== 'savings') {
        if (res_model === 'purchase.order') {
            if (this.state.stats.period && this.state.stats.period !== "0") {
                const today = new Date();
                const pastDate = new Date(today.getTime() - (parseInt(this.state.period) * 24 * 60 * 60 * 1000));
                const localPastStr = (new Date(pastDate - offset)).toISOString().split('T')[0];
                domain.push(['date_order', '>=', localPastStr], ['date_order', '<=', localTodayStr]);
            } else {
                if (startDate) domain.push(['date_order', '>=', startDate]);
                if (endDate) domain.push(['date_order', '<=', endDate]);
            }

            // تصفية إضافية لو المستخدم اختار مورد معين من الفلتر الرئيسي للـ Dashboard
            if (this.state.stats.filters && this.state.stats.filters.vendor_id !== "all") {
                domain.push(['partner_id', '=', parseInt(this.state.stats.filters.vendor_id)]);
            }
        }
    }

let views_array = view_mode.split(',').map(v => [false, v === 'list' ? 'tree' : v]);
    // 5. إطلاق الـ Action لفتح الشاشة المستهدفة بناءً على الخصائص المحددة أعلاه
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
/////////////////////////////////////////////////////////////////////////////////////////////////////

    async downloaddata(standardDomain = null) {
        if (this.state.stats.period === "0" || this.state.stats.period === 0) {
            if (this.state.stats.start_date && this.state.stats.end_date) {
                const start = new Date(this.state.stats.start_date);
                const end = new Date(this.state.stats.end_date);
                const td = new Date(this.state.stats.today_date);
                if (start > end || start > td || end > td) {
                    alert("Invalid Date Range! Reverting to last valid dates.");
                    this.state.stats.start_date = this.last_valid_start;
                    this.state.stats.end_date = this.last_valid_end;
                    sessionStorage.setItem("po_dashboard_start", this.last_valid_start || "");
                    sessionStorage.setItem("po_dashboard_end", this.last_valid_end || "");
                    return;
                }
            }
        }
        // const searchDomain = this.searchModel.domain || [];
        try {
            const data = await this.orm.call("wb.po.dashboard", "get_purchase_stats", [], {
                period: this.state.stats.period,
                domain: standardDomain || [],
                start_date: this.state.stats.start_date,
                end_date: this.state.stats.end_date,
                vendor_id: this.state.stats.filters.vendor_id,
                category_id: this.state.stats.filters.category_id,
                active_filters: this.state.stats.active_filters, group_by_list: this.state.group_by_list,
                custom_domain_list: this.state.custom_domain, search_query: this.state.search_query,


            });

            if (data) {
                this.state.stats.avg_savings = data.stats.avg_savings;
                this.state.stats.avg_lead_time = data.stats.avg_lead_time;
                this.state.stats.emergency_count = data.stats.emergency_count;
                this.state.stats.total_delay_days = data.stats.total_delay_days;
                this.state.stats.max_risk = data.stats.max_risk;
                this.state.stats.automation_rate = data.stats.automation_rate;


                this.lateVendorNames = data.late_vendor_names;
                this.lateVendorValues = data.late_vendor_values;
                this.vendorSpendingLabels = data.vendor_spending_labels;
                this.vendorSpendingValues = data.vendor_spending_values;
                this.orderStateData= data.order_state_data || { draft: [], purchase: [], done: [], cancel: [] };
                this.vendorNames= data.vendor_name || [];


                if (data.vendor_spending_labels && data.vendor_spending_labels.length > 0) {
                        this.state.top_vendor_name = data.vendor_spending_labels[0];
                }
             this.last_valid_start = this.state.stats.start_date;
            this.last_valid_end = this.state.stats.end_date;
            this.renderChart();

            }
        } catch (e) {
            this.state.stats.start_date = this.last_valid_start;
            this.state.stats.end_date = this.last_valid_end;
            throw e;
        }
    }
    // //////////////////////////////////////////////////////////////////////////////

    // تبديل حالة الفلاتر السريعة (Switches)
    async toggleFilter(filterName) {
    this.state.stats.active_filters[filterName] = !this.state.stats.active_filters[filterName];
    await this.downloaddata();

}

    // دالة تحديث البيانات عند تغيير أي فلتر
    async onApplyFilter() {
    await this.downloaddata();

}
    ////////////////////////////////////////////////////////////////////////////////////

    async onChangeStartDate(ev) {
        this.state.stats.start_date = ev.target.value;
        this.state.stats.period = "0";
        sessionStorage.setItem("po_dashboard_start", this.state.stats.start_date);
        sessionStorage.setItem("po_dashboard_period", "0");
        if (this.state.stats.start_date && this.state.stats.end_date) {
            await this.downloaddata();

        }
    }

    async onChangeEndDate(ev) {
        this.state.stats.end_date = ev.target.value;
          this.state.stats.period = "0";
        sessionStorage.setItem("po_dashboard_start", this.state.stats.start_date);
        sessionStorage.setItem("po_dashboard_period", "0");
        if (this.state.stats.start_date && this.state.stats.end_date) {
            await this.downloaddata();

        }
    }

    async onChangePeriod() {
        const period = this.state.stats.period;
        sessionStorage.setItem("po_dashboard_period", period);

        if (period !== "0") {
              const today = new Date();
            const startDate = new Date();
            startDate.setDate(today.getDate() - parseInt(period));

            const formatDate = (date) => date.toISOString().split('T')[0];
          this.state.stats.start_date = formatDate(startDate);
this.state.stats.end_date = formatDate(today);

            sessionStorage.setItem("po_dashboard_start",  this.state.stats.start_date)
            sessionStorage.setItem("po_dashboard_end",  this.state.stats.end_date)

        }

        await this.downloaddata();
        this.renderChart();
    }

    ////////////////////////////////////////////////////////////////////////////////////
    async downloadCustomExcel() {
        const data = await this.orm.call("wb.po.dashboard", "get_purchase_stats", [], {
            start_date: this.state.stats.start_date,
            end_date: this.state.stats.end_date,
        });
        const workbook = new ExcelJS.Workbook();
        const worksheet = workbook.addWorksheet('Purchase Order Pivot Data');
        worksheet.columns = [{width: 35}, {width: 25}];
        worksheet.addRow(["From Date", this.state.stats.start_date]);
        worksheet.addRow(["To Date", this.state.stats.end_date]);
        const headerRow = worksheet.addRow(["Key Performance Indicator", "Value"]);
        headerRow.eachCell((cell) => {
            cell.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'}};
            cell.font = {color: {argb: 'FFFFFFFF'}, bold: true, size: 13};
        });

        if (this.state.stats.show_avg_savings) worksheet.addRow(["Price Variance Status", data.stats.avg_savings + "%"]);
        if (this.state.stats.show_avg_lead_time) worksheet.addRow(["Avg Lead Time", data.stats.avg_lead_time + " Day(s)"]);
        if (this.state.stats.show_emergency_count) worksheet.addRow(["Urgent Requests", data.stats.emergency_count]);
        if (this.state.stats.show_total_delay_days) worksheet.addRow(["Avg Delivery Delay", data.stats.total_delay_days + "Day(s)"]);
        if (this.state.stats.show_max_risk) worksheet.addRow(["Total Orders", data.stats.max_risk + " %"])
        if (this.state.stats.show_automation_rate) worksheet.addRow(["Automation Rate", data.stats.automation_rate + " %"]);



        if (data.late_vendor_names && data.late_vendor_values) {
            const headerRow = worksheet.addRow(["Top 5 Late Vendors", "Value"]);
            headerRow.eachCell((cell) => {
                cell.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'}};
                cell.font = {color: {argb: 'FFFFFFFF'}, bold: true, size: 13};
            });
            for (let i = 0; i < data.late_vendor_names.length; i++) {
                worksheet.addRow([data.late_vendor_names[i], data.late_vendor_values[i]]);
            }
        }


        if (data.vendor_spending_labels && data.vendor_spending_values) {
            const headerRow = worksheet.addRow(["Top 5 Vendor Concentration", "Percentage (%)"]);
            headerRow.eachCell((cell) => {
                cell.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'}};
                cell.font = {color: {argb: 'FFFFFFFF'}, bold: true, size: 13};
            });
            const totalAmount = data.vendor_spending_values.reduce((a, b) => a + b, 0);
            for (let i = 0; i < data.vendor_spending_labels.length; i++) {
                let rawValue = data.vendor_spending_values[i];
                let percentage = totalAmount > 0 ? ((rawValue / totalAmount) * 100).toFixed(1) : 0;
                worksheet.addRow([data.vendor_spending_labels[i],percentage + "%"]);
            }
        }

        const buffer = await workbook.xlsx.writeBuffer();
        const blob = new Blob([buffer], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `PO_Analytics_Report${this.state.today_date}.xlsx`;
        link.click();
    }

    // ///////////////////////////////////////////////////////////////////////////////////////////////
    async downloadPdf() {
        const {jsPDF} = window.jspdf;
        const doc = new jsPDF();
        doc.setFontSize(22);
        doc.setTextColor(0, 123, 255);
        doc.text("PO Analysis", 14, 20);

        doc.setFontSize(11);
        doc.setTextColor(50, 50, 50);
        doc.text(`From Date: ${this.state.stats.start_date}      To Date: ${this.state.stats.end_date}`, 14, 30);


        const kpiBody = [
            ["Total Orders", this.state.stats.total_orders],
            ["Po Lead Time", this.state.stats.avg_lead_time + " %"],
            ["Urgent Requests", this.state.stats.emergency_count],
            ["Price Variance Status", this.state.stats.avg_savings + "%"],
            ["Avg Delivery Delay", this.state.stats.total_delay_days + "Day(s)"],
            ["Max Vendor Concentration", this.state.stats.max_risk + "%"],
            ["Automation Rate", this.state.stats.automation_rate + "%"],



        ];
        doc.autoTable({
            startY: 40,
            head: [['Key Performance Indicator', 'Value']],
            body: kpiBody,
            headStyles: {fillColor: [0, 123, 255], fontSize: 12},
            styles: {fontSize: 11, cellPadding: 4},
            alternateRowStyles: {fillColor: [245, 245, 245]}
        });

        // late vendor
        let currentY = doc.lastAutoTable.finalY+ 15;
        const lateVendorBody = [];
        if (this.lateVendorNames && this.lateVendorValues) {
        for (let i = 0; i < this.lateVendorNames.length; i++) {
            lateVendorBody.push([this.lateVendorNames[i], this.lateVendorValues[i] + " Day(s)"]);
            }
        }
        doc.autoTable({
        startY: currentY,
        head: [['Top 5 Late Vendors', 'Avg Delay Days']],
        body: lateVendorBody,
        headStyles: { fillColor: [255, 193, 7], },
        styles: { fontSize: 11, cellPadding: 4 }
    });

         // ///////////////////////////////////////////////////////////////////////////////////////////
     // state of order for each vendor
        currentY = doc.lastAutoTable.finalY+ 15;
        const orderStateBody = [];
        if (this.vendorNames && this.orderStateData) {
        for (let i = 0; i < this.vendorNames.length; i++) {
            const draftCount = this.orderStateData.draft[i] || 0;
           const confirmedCount = this.orderStateData.purchase[i] || 0;
        orderStateBody.push([this.vendorNames[i], `Draft: ${draftCount}, Confirmed: ${confirmedCount}`]);

            }
        }
        doc.autoTable({
        startY: currentY,
        head: [['Vendor Name', 'Order States (Count)']],
        body: orderStateBody,
        headStyles: { fillColor:[78, 115, 223] },
        styles: { fontSize: 11, cellPadding: 4 }
    });

        // /////////////////////////////////////////////////////////////////////////////
       //concentration vendor
       currentY = doc.lastAutoTable.finalY + 15;
    const concentrationBody = [];
    if (this.vendorSpendingLabels && this.vendorSpendingValues) {
        const totalAmount = this.vendorSpendingValues.reduce((a, b) => a + b, 0);

        for (let i = 0; i < this.vendorSpendingLabels.length; i++) {
            let val = this.vendorSpendingValues[i];
            let percentage = totalAmount > 0 ? ((val / totalAmount) * 100).toFixed(1) : 0;
            concentrationBody.push([this.vendorSpendingLabels[i], percentage + "%"]);
        }
    }
       doc.autoTable({
        startY: currentY,
        head: [['Vendor Concentration', 'Percentage (%)']],
        body: concentrationBody,
        headStyles: { fillColor: [78, 115, 223] },
        styles: { fontSize: 11, cellPadding: 4 }
    });
        doc.save(`PO_Analysis_${this.state.today_date}.pdf`);
    }

    // /////////////////////////////////////////////////////////////////////////////////////////////
    // Charts
    renderChart() {
        const delayCtx = this.delayRef.el;

        if (delayCtx && this.lateVendorValues) {
            if (delayCtx.chartInstance) {
                delayCtx.chartInstance.destroy();
            }


            delayCtx.chartInstance = new window.Chart(delayCtx, {
                type: "bar",
                data: {
                    labels: this.lateVendorNames,
                    datasets: [{
                        label: 'Delivery delays',
                        data: this.lateVendorValues,
                        backgroundColor: "#ffc107",
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick:(event, elements) => {
                        if (elements.length > 0) {
                            const index = elements[0].index;
                            const vendorName = this.vendorSpendingLabels[index];

                            if (vendorName && vendorName !== 'Other Vendors') {
                                this.openKpiAction("delay",vendorName);
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true
                        },
                        x: { ticks: { autoSkip: false } }
                    }
                }
            });
        }

        //     ///////////////////////////////////////////////////
        //state of order - bar chart
         const Ctx = this.orderRef.el;

        if (Ctx && this.orderStateData) {
            if (Ctx.chartInstance) {
                Ctx.chartInstance.destroy();
            }


            Ctx.chartInstance = new window.Chart(Ctx, {
                type: "bar",
                data: {
                    labels: this.vendorNames,
                    datasets: [
                       { label: 'Draft', data: this.orderStateData.draft, backgroundColor: '#adb5bd' },
                       { label: 'Confirmed', data:this.orderStateData.purchase, backgroundColor: '#007bff' },
                       { label: 'Done', data: this.orderStateData.done, backgroundColor: '#28a745' },
                        {label: 'Cancelled',data:  this.orderStateData.cancel, backgroundColor: '#dc3545' }
        ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    scales: {

                           x: {stacked: true},
                           y: {stacked: true, beginAtZero: true}
                    }
                }
            });
        }

        //     ////////////////////////////////////////////////////////////
        //     pie chart
        const vctx = this.vendorChartRef.el;
        if (vctx && this.vendorSpendingValues) {
            if (vctx.chartInstance) {
                vctx.chartInstance.destroy();
            }
            vctx.chartInstance = new window.Chart(vctx, {
                type: 'pie',
                data: {
                    labels: this.vendorSpendingLabels,
                    datasets: [{
                        data: this.vendorSpendingValues,
                        backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796'],
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick:(event, elements) => {
                        if (elements.length > 0) {
                            const index = elements[0].index;
                            const vendorName = this.vendorSpendingLabels[index];

                            if (vendorName && vendorName !== 'Other Vendors') {
                                this.openKpiAction("vendor_max_risk",vendorName);
                            }
                        }
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: function (context) {
                                    let label = context.label || '';
                                    let value = context.raw;
                                    let total = context.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                                    let percentage = ((value / total) * 100).toFixed(1) + '%';
                                    return label + ': ' + percentage;
                                }
                            }
                        },
                        legend: {position: 'bottom'}
                    }
                }
            });
        }
    }
}





PurchaseDashboard.template = "purchase_orders_dashboard_template";

registry.category("actions").add("PO_dashboard_client_tag", PurchaseDashboard);
