/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
// import {jsonrpc} from "@web/core/network/rpc_service";
const { Component,onWillStart,onMounted,useState,useRef} = owl;
export class PurchaseDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.vendorRef = useRef("vendor_chart_container");
        this.workloadRef = useRef("workload_chart_container");
        this.state=useState({
            period: 7,
            stats: {
               avg_savings: "0%",
                avg_lag: "0 Hrs",
                stability_rate: 0,
                emergency_count: 0
            }
        })
        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.downloaddata();
        });

        onMounted(() => {
            this.renderChart();
        });
    }
     async downloaddata()
            {
                try {
                  const data = await this.orm.call("purchase.order", "get_purchase_stats", [],{period: this.state.period});
console.log(data)

                    if (data) {
                        this.state.stats = data.stats;
                        // this.state.avg_savings = data.avg_savings;
                        //  this.state.avg_lag = data.avg_lag;
                       this.vendorLabels = data.vendor_labels;
                       this.chartVendorData = data.chart_vendor_data;
                       this.workloadLabels = data.work_load_labels;
                       this.workloadChartData = data.workload_chart_data;
                    }
                } catch (e) {
                    console.error("Error", e);
                }

            }
      async onChangePeriod(op){
            this.state.pariod=op.target.value;
             await this.downloaddata();
             await this.renderChart();
        }

        renderChart() {
        // bar
        const vendorCtx = this.vendorRef.el;
        if (vendorCtx && this.chartVendorData) {
            if (vendorCtx.chartInstance) vendorCtx.chartInstance.destroy();

            vendorCtx.chartInstance = new window.Chart(vendorCtx, {
                type: "bar",
                data: {
                    labels: this.vendorLabels,
                    datasets: [{
                        label: 'Savings %',
                        data: this.chartVendorData,
                        backgroundColor: "#28a745",
                       scales: { y: { beginAtZero: true } }
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false
                }
                  });

            // pie
                 const  workloadCtx =this.workloadRef.el;
        if (workloadCtx && this.workloadChartData) {
            if (workloadCtx.chartInstance) workloadCtx.chartInstance.destroy();

            workloadCtx.chartInstance = new window.Chart(workloadCtx, {
                type: "pie",
                data: {
                    labels: this.workloadLabels,
                    datasets: [{
                         label: 'Bill Issuance Delay (Hrs)',

                        data: this.workloadChartData,
                       backgroundColor: ['#007bff', '#dc3545', '#ffc107']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false
                }
            });
        }
    }}
}

PurchaseDashboard.template = "PurchaseDashboardMain";
registry.category("actions").add("purchase_dashboard_client_tag", PurchaseDashboard);