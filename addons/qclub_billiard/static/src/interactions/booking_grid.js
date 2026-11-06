import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

export class BookingGrid extends Interaction {
    static selector = ".o_qclub_booking_grid";

    dynamicContent = {
        ".o_qclub_booking_date": { "t-on-change": () => this.loadAvailability() },
    };

    setup() {
        this.requestNumber = 0;
        this.dateInput = this.el.querySelector(".o_qclub_booking_date");
        this.table = this.el.querySelector(".o_qclub_grid_table");
        this.message = this.el.querySelector(".o_qclub_grid_message");
        this.loginPrompt = this.el.querySelector(".o_qclub_login_prompt");
    }

    start() {
        if (this.el.dataset.loginRequired !== "1") {
            return this.loadAvailability();
        }
    }

    async loadAvailability() {
        const requestNumber = ++this.requestNumber;
        this.table.hidden = true;
        this.table.querySelector("thead").replaceChildren();
        this.table.querySelector("tbody").replaceChildren();
        this.message.textContent = _t("Loading availability…");
        this.loginPrompt.hidden = true;
        try {
            const result = await this.waitFor(rpc("/billiard/booking/occupancy", { date: this.dateInput.value }));
            if (requestNumber !== this.requestNumber) {
                return;
            }
            this.protectSyncAfterAsync(() => {
                if (result.error === "login_required") {
                    this.loginPrompt.hidden = false;
                    this.message.textContent = "";
                } else if (result.error) {
                    this.message.textContent = _t("Please choose a date within the available range.");
                } else {
                    this.dateInput.min = result.available_dates.min;
                    this.dateInput.max = result.available_dates.max;
                    this.renderGrid(result);
                }
            })();
        } catch {
            if (!this.isDestroyed && requestNumber === this.requestNumber) {
                this.protectSyncAfterAsync(() => {
                    this.message.textContent = _t("Availability could not be loaded. Please try again.");
                })();
            }
        }
    }

    renderGrid(result) {
        this.message.textContent = result.slots.length ? "" : _t("Closed on this business date.");
        const row = document.createElement("tr");
        const heading = document.createElement("th");
        heading.scope = "col";
        heading.className = "o_qclub_table_heading";
        heading.textContent = _t("Table / hourly price");
        row.append(heading);
        for (const [index, slot] of result.slots.entries()) {
            const column = document.createElement("th");
            column.scope = "col";
            column.dataset.slotIndex = String(index);
            column.textContent = slot.next_day ? `${slot.label} ${_t("(next day)")}` : slot.label;
            row.append(column);
        }
        this.table.querySelector("thead").replaceChildren(row);
        const body = document.createDocumentFragment();
        const format = new Intl.NumberFormat(document.documentElement.lang || "en-AU", {
            style: "currency", currency: result.currency,
        });
        const labels = { free: _t("Free"), occupied: _t("Occupied"), past: _t("Past") };
        for (const table of result.tables) {
            const tableRow = document.createElement("tr");
            tableRow.className = "o_qclub_table_row";
            tableRow.dataset.tableId = String(table.id);
            const name = document.createElement("th");
            name.scope = "row";
            name.className = "o_qclub_table_heading";
            // textContent keeps names and table types inert, including HTML-like input.
            name.textContent = `${table.name} · ${table.type} · ${format.format(table.hourly_price)} / ${_t("hour")}`;
            tableRow.append(name);
            for (const [index, state] of table.slots.entries()) {
                const cell = document.createElement("td");
                cell.className = `o_qclub_slot o_qclub_slot_${state}`;
                cell.dataset.tableId = String(table.id);
                cell.dataset.slotIndex = String(index);
                cell.dataset.state = state;
                cell.textContent = state === "free" ? format.format(table.hourly_price) : labels[state];
                cell.setAttribute("aria-label", `${table.name}, ${result.slots[index].label}, ${labels[state]}`);
                if (state !== "free") {
                    cell.setAttribute("aria-disabled", "true");
                }
                tableRow.append(cell);
            }
            body.append(tableRow);
        }
        this.table.querySelector("tbody").replaceChildren(body);
        this.table.hidden = false;
    }
}

registry.category("public.interactions").add("qclub_billiard.booking_grid", BookingGrid);
