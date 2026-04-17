/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useState } from "@odoo/owl";

class MedicalStockView extends Component {
    static template = "medical_inventory.StockView";

    setup() {
        this.actionService = useService("action");
        this.state = useState({
            loading: true,
            error: false,
            data: null,
            search: '',
            selectedLocation: 'all',
            selectedCategory: 'all',
            view: 'cards', // 'cards' or 'table'
        });
        onMounted(() => this.loadData());
    }

    async loadData() {
        try {
            const res = await fetch('/medical_inventory/stock_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: {} }),
            });
            const json = await res.json();
            if (json.result) {
                this.state.data = json.result;
                this.state.loading = false;
            } else {
                this.state.error = true;
                this.state.loading = false;
            }
        } catch (e) {
            this.state.error = true;
            this.state.loading = false;
        }
    }

    get filteredLocations() {
        if (!this.state.data) return [];
        let locs = this.state.data.locations;

        if (this.state.selectedLocation !== 'all') {
            locs = locs.filter(l => l.id == this.state.selectedLocation);
        }

        const search = this.state.search.toLowerCase().trim();
        if (!search && this.state.selectedCategory === 'all') return locs;

        return locs.map(loc => {
            let products = loc.products;
            if (search) {
                products = products.filter(p =>
                    p.name.toLowerCase().includes(search) ||
                    p.ref.toLowerCase().includes(search) ||
                    p.category.toLowerCase().includes(search)
                );
            }
            if (this.state.selectedCategory !== 'all') {
                products = products.filter(p => p.category === this.state.selectedCategory);
            }
            if (products.length === 0) return null;
            return { ...loc, products,
                product_count: products.length,
                total_qty: products.reduce((s, p) => s + p.qty, 0),
                total_value: products.reduce((s, p) => s + p.value, 0),
            };
        }).filter(Boolean);
    }

    get allCategories() {
        if (!this.state.data) return [];
        const cats = new Set();
        this.state.data.locations.forEach(l => l.products.forEach(p => cats.add(p.category)));
        return [...cats].sort();
    }

    setView(v) { this.state.view = v; }
    setSearch(e) { this.state.search = e.target.value; }
    setLocation(e) { this.state.selectedLocation = e.target.value; }
    setCategory(e) { this.state.selectedCategory = e.target.value; }

    stockStatus(qty) {
        if (qty <= 0) return 'empty';
        if (qty <= 5) return 'critical';
        if (qty <= 20) return 'low';
        return 'good';
    }

    stockLabel(qty) {
        if (qty <= 0) return 'Empty';
        if (qty <= 5) return 'Critical';
        if (qty <= 20) return 'Low';
        return 'OK';
    }

    fmt(n) { return Number(n).toLocaleString(); }
    fmtMoney(n) { return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

    navigate(action) {
        this.actionService.doAction('medical_inventory.' + action);
    }
}

registry.category("actions").add("medical_stock_view", MedicalStockView);
