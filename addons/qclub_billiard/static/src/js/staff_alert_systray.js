/** @odoo-module **/

import { Component, EventBus, onWillStart, useState, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

// Both components share one subscription owner, so closing the board cannot
// unsubscribe the systray. Company switching reloads the backend and this service.
registry.category("services").add("qclub_realtime", {
    dependencies: ["bus_service", "orm"],
    start(env, { bus_service: bus, orm }) {
        const events = new EventBus();
        let watermark = Infinity;
        let connected = false;
        let generation = 0;
        const context = () => user.context;
        const subscription = () => orm.call("qclub.table", "get_staff_realtime_subscription", [], {
            context: context(),
        });
        const ready = (async () => {
            const enabled = await user.hasGroup("qclub_billiard.group_billiard_staff");
            if (!enabled) {
                return false;
            }
            const data = await subscription();
            watermark = data.last_notification_id;
            connected = bus.workerState === "CONNECTED";
            bus.subscribe("qclub.board_update", (payload) => events.trigger("qclub.board_update", payload));
            bus.subscribe("qclub.alert", (payload, { id }) => {
                if (connected && id > watermark) {
                    events.trigger("qclub.alert", payload);
                }
            });
            const disconnect = () => {
                connected = false;
                generation++;
            };
            const connect = async () => {
                // Odoo bus can replay buffered messages after reconnect. Ignore
                // those for ephemeral staff toasts using a server-side bus id.
                const current = ++generation;
                connected = false;
                const latest = await subscription();
                if (current === generation) {
                    watermark = latest.last_notification_id;
                    connected = true;
                }
            };
            bus.addEventListener("BUS:DISCONNECT", disconnect);
            bus.addEventListener("BUS:RECONNECTING", disconnect);
            bus.addEventListener("BUS:CONNECT", connect);
            bus.addEventListener("BUS:RECONNECT", connect);
            for (const channel of data.channels) {
                // Worker initialization must not delay the board's initial RPC.
                bus.addChannel(channel);
            }
            return true;
        })();
        return Object.assign(events, { ready, context });
    },
});

export class StaffAlertSystray extends Component {
    static template = xml`<span t-if="state.enabled" class="d-flex align-items-center px-2"
        title="Live staff alerts" aria-label="Live staff alerts"><i class="fa fa-bell-o"/></span>`;
    static props = {};

    setup() {
        this.realtime = useService("qclub_realtime");
        this.notification = useService("notification");
        this.state = useState({ enabled: false });
        onWillStart(async () => { this.state.enabled = await this.realtime.ready; });
        useBus(this.realtime, "qclub.alert", ({ detail: alert }) => {
            const messages = {
                booking_submitted: `New booking ${alert.booking_name} awaiting deposit`,
                deposit_confirmed: `Deposit received for booking ${alert.booking_name}`,
                cancelled: `Booking ${alert.booking_name} cancelled`,
                player_joined: `New player accepted for booking ${alert.booking_name}`,
            };
            if (Object.hasOwn(messages, alert.kind)) {
                const time = (value) => new Intl.DateTimeFormat("en-AU", {
                    timeZone: "Australia/Adelaide", month: "short", day: "numeric",
                    hour: "numeric", minute: "2-digit",
                }).format(new Date(`${value}Z`));
                this.notification.add(
                    `${messages[alert.kind]} · ${alert.table_name} · ${time(alert.start)} – ${time(alert.end)}`,
                    { title: "Billiards", type: "info", sticky: false }
                );
            }
        });
    }
}

registry.category("systray").add("qclub_billiard.StaffAlertSystray", {
    Component: StaffAlertSystray,
}, { sequence: 30 });
