/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";

export class TableBoard extends Component {
    static template = "qclub_billiard.TableBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.realtime = useService("qclub_realtime");
        this.state = useState({ tables: [], loading: true, error: false });
        this.pending = new Set();
        this.destroyed = false;
        // Serialize incremental reads so an older response cannot replace a newer
        // snapshot. Events arriving during the initial read are drained afterwards.
        this.updates = Promise.resolve();
        onWillUnmount(() => { this.destroyed = true; });
        onWillStart(async () => { await this.realtime.ready; });
        useBus(this.realtime, "qclub.board_update", ({ detail }) => {
            this.pending.add(detail.table_id);
            if (this.loaded) {
                this.refresh();
            }
        });
        onMounted(async () => {
            try {
                this.state.tables = await this.read();
                this.loaded = true;
                this.state.loading = false;
                this.refresh();
            } catch (error) {
                this.state.loading = false;
                this.state.error = "Could not load Table Board. Refresh to try again.";
                console.error(error);
            }
        });
    }

    read(ids) {
        return this.orm.call("qclub.table", "get_table_board", ids === undefined ? [] : [ids], {
            context: this.realtime.context(),
        });
    }

    refresh() {
        this.updates = this.updates.then(async () => {
            if (this.destroyed || !this.pending.size) {
                return;
            }
            const ids = [...this.pending];
            this.pending.clear();
            const rows = await this.read(ids);
            if (this.destroyed) {
                return;
            }
            const unchanged = this.state.tables.filter((table) => !ids.includes(table.id));
            this.state.tables = [...unchanged, ...rows].sort((a, b) => a.name.localeCompare(b.name));
        }).catch((error) => {
            // Keep the last snapshot visible and let Odoo report the RPC failure.
            this.env.services.notification.add("Could not update Table Board. Refresh to try again.", {
                type: "warning",
            });
            console.error(error);
        });
    }

    timeLabel(value) {
        return new Intl.DateTimeFormat("en-AU", {
            timeZone: "Australia/Adelaide", hour: "numeric", minute: "2-digit",
        }).format(new Date(value));
    }
}

registry.category("actions").add("qclub_table_board", TableBoard);
