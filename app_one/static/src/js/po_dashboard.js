/* @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { SearchModel } from "@web/search/search_model";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSubEnv } from "@odoo/owl";

const { Component, onWillStart, onMounted, useState, useRef } = owl;

export class PurchaseDashboard extends Component {
    static components = { SearchBar };
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


        this.employeeRef = useRef("employee_chart_container");
        this.delayRef = useRef("delays_chart_container"); // مرجع الرسم البياني

        const today = new Date();
        const lastWeek = new Date(today);
        lastWeek.setDate(lastWeek.getDate() - 7);
        const formatDate = (date) => date.toISOString().split('T')[0];
        const todayStr = formatDate(today);
        const lastWeekStr = formatDate(lastWeek);
        const savedStartDate = sessionStorage.getItem("po_dashboard_start") || lastWeekStr;
        const savedEndDate = sessionStorage.getItem("po_dashboard_end") || todayStr;

        this.state = useState({
            stats: {
                employeeData: [],
                avg_savings: 0,
                avg_lead_time: 0.0,
                emergency_count: 0,
                total_orders: 0,
                total_delay_days: 0,
                start_date: savedStartDate,
                end_date: savedEndDate,
                today_date: todayStr,
                show_total_orders: true,
                show_avg_savings: true,
                show_avg_lead_time: true,
                show_emergency_count: true,
                show_total_delay_days: true,
            },
            showSidebar: false,
        });

        this.last_valid_start = savedStartDate;
        this.last_valid_end = savedEndDate;


        onWillStart(async () => {
    //         await this.searchModel.load({
    //         resModel: "purchase.order",
    //         views: [[await this.env.ref("app_one.view_purchase_dashboard_search"), "search"]],
    // });
            const viewData = await this.orm.searchRead("ir.model.data", [
        ["module", "=", "app_one"],
        ["name", "=", "view_purchase_dashboard_search"]
    ], ["res_id"]);

    const viewId = viewData.length > 0 ? viewData[0].res_id : false;

    // 2. تحميل الـ searchModel باستخدام الـ ID الرقمي
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

openKpiAction(type) {
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
    switch(type) {
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
            actionData.context = { 'pivot_measures': ['is_emergency'],};
            actionData.domain = [...activeDomain,['is_emergency', '=', true], ['state', '!=', 'cancel']];
            break;

           case 'lead_time':
            actionData.name = 'Avg Lead Time';
            actionData.view_mode = 'pivot,tree';
            actionData.domain = [...activeDomain,['state', 'in', ['purchase', 'done']], ['date_approve', '!=', false]];
            actionData.context = {
                 'pivot_row_groupby': ['user_id'], // التجميع حسب الموظف (المستخدم)
                 'pivot_measures': ['po_lead_time'], // قياس وقت الاعتماد
    };
        break;

        case 'delay':
            actionData.name = 'Vendor Delivery Delay';
            actionData.view_mode = 'pivot,tree';
            actionData.domain = [...activeDomain,['state', 'in', ['purchase', 'done']]];
            actionData.context = {
                'pivot_row_groupby': ['partner_id'],
                'pivot_measures': ['vendor_delays'],
            };
            break;

        default:
            actionData.views = [[false, 'tree'], [false, 'form']];
            actionData.view_mode = 'tree,form';
            actionData.name = 'Purchase Orders';
    }

    this.actionService.doAction(actionData);
}




    async downloaddata() {
         const searchDomain = this.searchModel.domain || [];
        try {
            if (this.state.stats.start_date > this.state.stats.end_date) {
                alert("Start date must be before end date");
                return;
            }
            const data = await this.orm.call("wb.po.dashboard", "get_purchase_stats", [], {
                domain: searchDomain,
                start_date: this.state.stats.start_date,
                end_date: this.state.stats.end_date,

            });

            if (data) {
                this.state.stats.avg_savings = data.stats.avg_savings;
                this.state.stats.avg_lead_time = data.stats.avg_lead_time;
                this.state.stats.emergency_count = data.stats.emergency_count;
                this.state.stats.total_orders = data.stats.total_orders;
                this.state.stats.total_delay_days = data.stats.total_delay_days;

                this.employeeNames = data.employee_names;
                this.employeeDelays = data.employee_delays;
                this.lateVendorNames = data.late_vendor_names;
                this.lateVendorValues = data.late_vendor_values;


            }
        } catch (e) {
            this.state.stats.start_date = this.last_valid_start;
            this.state.stats.end_date = this.last_valid_end;
            throw e;
        }
    }

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


     async downloadCustomExcel() {
        const data = await this.orm.call("wb.po.dashboard", "get_purchase_stats", [], {
            start_date: this.state.stats.start_date,
            end_date: this.state.stats.end_date,
        });
        const workbook = new ExcelJS.Workbook();
        const worksheet = workbook.addWorksheet('Purchase Order Pivot Data');
        worksheet.columns = [ {width: 35}, {width: 25} ];
        worksheet.addRow(["From Date", this.state.stats.start_date]);
        worksheet.addRow(["To Date", this.state.stats.end_date]);
        const headerRow = worksheet.addRow(["Key Performance Indicator", "Value"]);
        headerRow.eachCell((cell) => {
            cell.fill = { type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'} };
            cell.font = { color: {argb: 'FFFFFFFF'}, bold: true, size: 13 };
        });

        if (this.state.stats.show_avg_savings) worksheet.addRow(["Price Variance Status", data.stats.avg_savings + "%"]);
        if (this.state.stats.show_avg_lead_time) worksheet.addRow(["Avg Lead Time", data.stats.avg_lead_time + " Day(s)"]);
        if (this.state.stats.show_emergency_count) worksheet.addRow(["Urgent Requests", data.stats.emergency_count]);
        if (this.state.stats.show_total_delay_days) worksheet.addRow(["Avg Delivery Delay", data.stats.total_delay_days + "Day(s)"]);
        // if (this.state.stats.show_total_orders) worksheet.addRow(["Total Orders", data.stats.total_orders + " Day(s)"]);




        if (data.late_vendor_names && data.late_vendor_values) {
             const headerRow = worksheet.addRow(["Top 5 Late Vendors", "Value"]);
             headerRow.eachCell((cell) => {
                     cell.fill = { type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'} };
                     cell.font = { color: {argb: 'FFFFFFFF'}, bold: true, size: 13 };
                     });
            for (let i = 0; i < data.late_vendor_names.length; i++) {
                    worksheet.addRow([data.late_vendor_names[i], data.late_vendor_values[i]]);
            }
        }

                if (data.employee_names && data.employee_delays) {
             const headerRow = worksheet.addRow(["Top 5 Late Vendors", "Value"]);
             headerRow.eachCell((cell) => {
                     cell.fill = { type: 'pattern', pattern: 'solid', fgColor: {argb: '17ac39'} };
                     cell.font = { color: {argb: 'FFFFFFFF'}, bold: true, size: 13 };
                     });
            for (let i = 0; i < data.employee_names.length; i++) {
                    worksheet.addRow([data.employee_names[i], data.employee_delays[i]]);
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
        let currentY = 30;
        currentY += 7;
        doc.text(`From Date: ${this.state.stats.start_date}      To Date: ${this.state.stats.end_date}`, 14, currentY);
        currentY += 7;

        const kpiBody = [
            ["Total Orders", this.state.stats.total_orders],
            ["Po Lead Time", this.state.stats.avg_lead_time + " %"],
            ["Urgent Requests", this.state.stats.emergency_count],
            ["Price Variance Status", this.state.stats.avg_savings + "%"],
            ["Avg Delivery Delay", this.state.stats.total_delay_days + "Day(s)"],


        ];
        doc.autoTable({
            startY: currentY + 3,
            head: [['Key Performance Indicator', 'Value']],
            body: kpiBody,
            headStyles: {fillColor: [0, 123, 255], fontSize: 12},
            styles: {fontSize: 11, cellPadding: 4},
            alternateRowStyles: {fillColor: [245, 245, 245]}
        });

        const chartBody = [];
        if (this.lateVendorNames && this.lateVendorValues) {
            for (let i = 0; i < this.lateVendorNames.length; i++) {
                chartBody.push([this.lateVendorNames[i], this.lateVendorValues[i] + " Day(s)"]);
            }
        }
        if (this.employeeNames && this.employeeDelays) {
            for (let i = 0; i < this.employeeNames.length; i++) {
                chartBody.push([this.employeeNames[i], this.employeeDelays[i] + " Day(s)"]);
            }
        }
            doc.autoTable({
                startY: doc.lastAutoTable.finalY + 15,
                head: [[`Top 5 Late Vendors`, 'Number of days']],
                body: chartBody,
                headStyles: {fillColor: [0, 123, 255], fontSize: 12},
                styles: {fontSize: 11, cellPadding: 4},
                alternateRowStyles: {fillColor: [245, 245, 245]}
            });
        doc.save(`PO_Analysis_${this.state.today_date}.pdf`);
    }

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
                        label: 'Delivery delays (Avg Days)',
                        data: this.lateVendorValues,
                        backgroundColor: "#ffc107",
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }

    //     ///////////////////////////////////////////////////

       const ctx = this.employeeRef.el;

        if (ctx && this.employeeDelays) {
            if (ctx.chartInstance) {
                ctx.chartInstance.destroy();
            }


            ctx.chartInstance = new window.Chart(ctx, {
                type: "bar",
                data: {
                    labels: this.employeeNames,
                    datasets: [{
                        label: 'Slowest 5 Employees (Avg Days)',
                        data: this.employeeDelays,
                        backgroundColor: "#ef4444",
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    },
                    indexAxis: 'y'
                }
            });
        }

    }

}


PurchaseDashboard.template = "purchase_orders_dashboard_template";

registry.category("actions").add("PO_dashboard_client_tag", PurchaseDashboard);