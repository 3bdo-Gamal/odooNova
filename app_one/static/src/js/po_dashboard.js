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


        this.vendorRef = useRef("vendor_chart_container");
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
                avg_savings: 0,
                stability_rate: 0,
                emergency_count: 0,
                total_orders: 0,
                total_delay_days: 0,
                start_date: savedStartDate,
                end_date: savedEndDate,
                today_date: todayStr,
                show_total_orders: true,
                show_avg_savings: true,
                show_stability_rate: true,
                show_emergency_count: true,
                show_total_delay_days: false,
                date_from: "",
                date_to: "",
                period: "30"
            },
            showSidebar: false,
        });

        this.last_valid_start = savedStartDate;
        this.last_valid_end = savedEndDate;


        onWillStart(async () => {
            await this.searchModel.load({
            resModel: "purchase.order",
            views: [[false, "search"]],
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
                this.state.stats.stability_rate = data.stats.stability_rate;
                this.state.stats.emergency_count = data.stats.emergency_count;
                this.state.stats.total_orders = data.stats.total_orders;
                this.state.stats.total_delay_days = data.stats.total_delay_days;

                this.vendorLabels = data.vendor_labels;
                this.chartVendorData = data.chart_vendor_data;
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

        if (this.state.stats.show_total_orders) worksheet.addRow(["Total Orders", data.stats.total_orders]);
        if (this.state.stats.show_stability_rate) worksheet.addRow(["Modification Rate", data.stats.stability_rate + " %"]);
        if (this.state.stats.show_emergency_count) worksheet.addRow(["Urgent Requests", data.stats.emergency_count]);
        if (this.state.stats.show_avg_savings) worksheet.addRow(["Price Variance Status", data.stats.avg_savings + "%"]);
        if (this.state.stats.show_total_delay_days) worksheet.addRow(["Avg Delivery Delay", data.stats.total_delay_days + "Day(s)"]);




        if (data.late_vendor_names && data.late_vendor_values) {
            for (let i = 0; i < data.late_vendor_names.length; i++) {
                    worksheet.addRow([data.late_vendor_names[i], data.late_vendor_values[i]]);
            }
        }

        const buffer = await workbook.xlsx.writeBuffer();
        const blob = new Blob([buffer], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `PO_Analytics_Report${this.state.today_date}.xlsx`;
        link.click();
    }


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
            ["Modification Rate", this.state.stats.stability_rate + " %"],
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
                chartBody.push([this.lateVendorNames[i], this.lateVendorValues[i] + " Hrs"]);
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

            // تم تصليح الأقواس هنا
            delayCtx.chartInstance = new window.Chart(delayCtx, {
                type: "bar",
                data: {
                    labels: this.lateVendorNames,
                    datasets: [{
                        label: 'delays Day(s)',
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
    }

}


PurchaseDashboard.template = "purchase_orders_dashboard_template";

registry.category("actions").add("PO_dashboard_client_tag", PurchaseDashboard);