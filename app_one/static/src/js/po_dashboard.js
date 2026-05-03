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

const savedPeriod = sessionStorage.getItem("hr_dashboard_period") || "30";
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

        this.state = useState({
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
    pay_paid: false
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
            this.state.stats.filter_options = options;

            const viewData = await this.orm.searchRead("ir.model.data", [
                ["module", "=", "app_one"],
                ["name", "=", "view_purchase_dashboard_search"]
            ], ["res_id"]);

            const viewId = viewData.length > 0 ? viewData[0].res_id : false;

            await this.searchModel.load({
                resModel: "purchase.order",
                views: [[viewId, "search"]],
            });


            await loadJS("/web/static/lib/Chart/Chart.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.3.0/exceljs.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js");
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js");

            await this.downloaddata();
        });

        onMounted(() => {
            this.renderChart();
        });
    }

//     //////////////////////////////////////////////////////////////
toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
        sessionStorage.setItem("po_dashboard_sidebar", this.state.showSidebar);
    }


//     //////////////////////////////////////////////////////////////

    openKpiAction(type,vendorName = null) {
        let actionData = {
            type: 'ir.actions.act_window',
            res_model: 'purchase.order',
            views: [[false, 'list'], [false, 'pivot'], [false, 'form']],
            view_mode: 'tree,pivot,form',
            target: 'current',
            context: {}
        };
        let activeDomain = [

            ['date_order', '>=', this.state.stats.start_date],
            ['date_order', '<=', this.state.stats.end_date]
        ];
        switch (type||vendorName) {
            case 'savings':
                actionData.name = 'Saving Analysis';
                actionData.res_model = 'purchase.requisition';
                actionData.view_mode = 'tree,form';
                actionData.views = [[false, 'list'], [false, 'form']];
                actionData.context = {
                    'search_default_ongoing': 1,
                    'pivot_row_groupby': ['product_id'], // تجميع بالمنتج
                    'pivot_measures': ['price_variance'],
                };
                actionData.domain = [
                    ['state', '!=', 'cancel'],
                    ['type_id.exclusive', '=', 'exclusive']
                ];
                break;


            case 'emergency':
                actionData.name = 'Uragant Orders';
                actionData.view_mode = 'tree,form';
                actionData.context = {'pivot_measures': ['is_emergency'],};
                actionData.domain = [...activeDomain, ['is_emergency', '=', true], ['state', '!=', 'cancel']];
                break;

            case 'lead_time':
                actionData.name = 'Avg Lead Time';
                actionData.view_mode = 'pivot,tree';
                actionData.domain = [...activeDomain, ['state', 'in', ['purchase', 'done']], ['date_approve', '!=', false]];
                actionData.context = {
                    'pivot_row_groupby': ['user_id'],
                    'pivot_measures': ['po_lead_time'],
                };
                break;

            case 'delay':
                actionData.name = 'Vendor Delivery Delay';
                actionData.view_mode = 'pivot,tree';
                actionData.domain = [...activeDomain, ['state', 'in', ['purchase', 'done']]];
                actionData.context = {
                    'pivot_row_groupby': ['partner_id'],
                    'pivot_measures': ['vendor_delays'],
                };
                break;

            case 'vendor_max_risk':
                const targetVendor = vendorName || this.state.top_vendor_name;
                actionData.name = 'Top Concentrated Vendor: ' + (targetVendor || '');
                actionData.view_mode = 'pivot,tree,form';
                if (targetVendor) {
                    actionData.domain = [...activeDomain,
                                        ['partner_id', '=', targetVendor],
                                        ['state', 'in', ['purchase', 'done']]];
                } else {
                    actionData.domain = [...activeDomain, ['state', 'in', ['purchase', 'done']]];
                }

                actionData.context = {
                  'pivot_row_groupby': ['partner_id'],
                    'pivot_measures': ['amount_total'],
                };
                break;

            case 'automation_rate':
                actionData.name = 'PO Automation Rate';
                actionData.view_mode = 'pivot,tree';
                actionData.domain = [...activeDomain, ['state', 'in', ['purchase', 'done']]];
                break;


            default:
                actionData.views = [[false, 'tree'], [false, 'form']];
                actionData.view_mode = 'tree,form';
                actionData.name = 'Purchase Orders';
        }

        this.actionService.doAction(actionData);
    }


    async downloaddata() {
        if (this.state.stats.period === "0" || this.state.stats.period === 0) {
            if (this.state.stats.start_date && this.state.stats.end_date) {
                const start = new Date(this.state.stats.start_date);
                const end = new Date(this.state.stats.end_date);
                const td = new Date(this.state.stats.today_date);
                if (start > end || start > td || end > td) {
                    alert("Invalid Date Range! Reverting to last valid dates.");
                    this.state.stats.start_date = this.last_valid_start;
                    this.state.stats.end_date = this.last_valid_end;
                    sessionStorage.setItem("hr_dashboard_start", this.last_valid_start || "");
                    sessionStorage.setItem("hr_dashboard_end", this.last_valid_end || "");
                    return;
                }
            }
        }
        const searchDomain = this.searchModel.domain || [];
        try {
            if (this.state.stats.start_date > this.state.stats.end_date) {
                alert("Start date must be before end date");
                return;
            }
            const data = await this.orm.call("wb.po.dashboard", "get_purchase_stats", [], {
                domain: this.searchModel.domain || [],
                start_date: this.state.stats.start_date,
                end_date: this.state.stats.end_date,
                vendor_id: this.state.stats.filters.vendor_id,
            category_id: this.state.stats.filters.category_id,
            active_filters: this.state.stats.active_filters,

            });

            if (data) {
                this.state.stats.avg_savings = data.stats.avg_savings;
                this.state.stats.avg_lead_time = data.stats.avg_lead_time;
                this.state.stats.emergency_count = data.stats.emergency_count;
                this.state.stats.total_orders = data.stats.total_orders;
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
    this.renderChart();
}

    // دالة تحديث البيانات عند تغيير أي فلتر
    async onApplyFilter() {
    await this.downloaddata();
    this.renderChart();
}
    ////////////////////////////////////////////////////////////////////////////////////

    async onChangeStartDate(ev) {
        this.state.stats.start_date = ev.target.value;
        sessionStorage.setItem("po_dashboard_start", this.state.stats.start_date);
        if (this.state.stats.start_date && this.state.stats.end_date) {
            await this.downloaddata();
            this.renderChart();
        }
    }

    async onChangeEndDate(ev) {
        this.state.stats.end_date = ev.target.value;
        sessionStorage.setItem("po_dashboard_end", this.state.stats.end_date);
        if (this.state.stats.start_date && this.state.stats.end_date) {
            await this.downloaddata();
            this.renderChart();
        }
    }

    async onChangePeriod() {
        const period = this.state.stats.period;

        const today = new Date();
        const formatDate = (date) => date.toISOString().split('T')[0];

        if (period !== "0") {
            const startDate = new Date();
            startDate.setDate(today.getDate() - parseInt(period));

            this.state.stats.start_date = formatDate(startDate);
            this.state.stats.end_date = formatDate(today);
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
        headStyles: { fillColor: [255, 193, 7], textColor: [0, 0, 0] }, // لون أصفر مثل الرسمة
        styles: { fontSize: 11, cellPadding: 4 }
    });

         // ///////////////////////////////////////////////////////////////////////////////////////////
     // state of order for each vendor
        currentY = doc.lastAutoTable.finalY+ 15;
        const orderStateBody = [];
        if (this.vendorNames && this.orderStateData) {
        for (let i = 0; i < this.vendorNames.length; i++) {
            lateVendorBody.push([this.vendorNames[i], this.orderStateData[i] + " Day(s)"]);
            }
        }
        doc.autoTable({
        startY: currentY,
        head: [['State of Order', 'Avg Delay Days']],
        body: orderStateBody,
        headStyles: { fillColor: [255, 200, 7], textColor: [0, 0, 0] },
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
