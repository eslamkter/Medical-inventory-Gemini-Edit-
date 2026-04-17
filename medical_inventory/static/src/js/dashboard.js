/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useState } from "@odoo/owl";

class MedicalDashboard extends Component {
    static template = "medical_inventory.Dashboard";

    setup() {
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, data: null, error: false });
        onMounted(() => this.loadData());
    }

    async loadData() {
        try {
            const response = await fetch('/medical_inventory/dashboard_data', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: {} }),
            });
            const json = await response.json();
            if (json.result) {
                this.state.data = json.result;
                this.state.loading = false;
                setTimeout(() => this.drawChart(), 200);
            } else {
                this.state.error = true;
                this.state.loading = false;
            }
        } catch (e) {
            this.state.error = true;
            this.state.loading = false;
        }
    }

    async navigateTo(actionXmlId) {
        try {
            await this.actionService.doAction(actionXmlId);
        } catch(e) {
            this.notification.add('Navigation error: ' + actionXmlId, { type: 'warning' });
        }
    }

    drawChart() {
        const canvas = document.getElementById('o_spend_chart');
        if (!canvas || !this.state.data) return;
        const data = this.state.data.monthly_spend;
        if (!data || data.length === 0) return;
        const W = canvas.parentElement.offsetWidth - 40 || 500;
        canvas.width = W; canvas.height = 200;
        const ctx = canvas.getContext('2d');
        const pad = { top: 20, right: 10, bottom: 36, left: 65 };
        const cW = W - pad.left - pad.right;
        const cH = 200 - pad.top - pad.bottom;
        const maxVal = Math.max(...data.map(d => d.value), 1);
        ctx.clearRect(0, 0, W, 200);
        ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const y = pad.top + cH - (cH * i / 4);
            ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + cW, y); ctx.stroke();
            ctx.fillStyle = '#94a3b8'; ctx.font = '10px Segoe UI'; ctx.textAlign = 'right';
            ctx.fillText('$' + Math.round(maxVal * i / 4).toLocaleString(), pad.left - 5, y + 4);
        }
        const bW = Math.max(10, Math.floor(cW / data.length) - 8);
        data.forEach((d, i) => {
            const x = pad.left + i * (cW / data.length) + 4;
            const bH = d.value > 0 ? Math.max(3, (d.value / maxVal) * cH) : 3;
            const y = pad.top + cH - bH;
            const g = ctx.createLinearGradient(x, y, x, y + bH);
            g.addColorStop(0, '#1565c0'); g.addColorStop(1, '#42a5f5');
            ctx.fillStyle = g;
            ctx.fillRect(x, y, bW, bH);
            ctx.fillStyle = '#64748b'; ctx.font = '10px Segoe UI'; ctx.textAlign = 'center';
            ctx.fillText(d.month.split(' ')[0], x + bW / 2, pad.top + cH + 16);
        });
    }

    fmt(n) { return n !== undefined ? Number(n).toLocaleString() : '0'; }
    fmtMoney(n) {
        return n !== undefined
            ? Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : '0.00';
    }
    barPct(val, max) {
        if (!max || max === 0) return '2%';
        return Math.max(2, Math.round((val / max) * 100)) + '%';
    }
}

registry.category("actions").add("medical_inventory_dashboard", MedicalDashboard);
