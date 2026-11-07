import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

export class BookingGrid extends Interaction {
    static selector = ".o_qclub_booking_grid";

    dynamicContent = {
        _root: {
            "t-on-click": (ev) => {
                const cell = ev.target.closest(".o_qclub_slot_free");
                if (cell && this.el.contains(cell)) {
                    this.selectSlot(cell);
                }
            },
            "t-on-keydown": (ev) => {
                const cell = ev.target.closest(".o_qclub_slot_free");
                if (cell && (ev.key === "Enter" || ev.key === " ")) {
                    ev.preventDefault();
                    this.selectSlot(cell);
                }
            },
        },
        ".o_qclub_clear": { "t-on-click": () => this.clearSelection() },
        ".o_qclub_book": { "t-on-click": () => this.book() },
        ".o_qclub_booking_date": { "t-on-change": () => this.loadAvailability() },
    };

    setup() {
        this.requestNumber = 0;
        this.quoteNumber = 0;
        this.selection = null;
        this.restore = new URLSearchParams(window.location.search);
        this.summary = this.el.querySelector(".o_qclub_selection");
        this.bookButton = this.el.querySelector(".o_qclub_book");
        this.error = this.el.querySelector(".o_qclub_selection_error");
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

    showAlert(text) {
        // Conflicts happen after scrolling down to Book: make the outcome visible.
        this.message.textContent = text;
        this.message.classList.add("alert", "alert-danger", "o_qclub_alert");
        this.message.setAttribute("role", "alert");
        this.message.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    clearAlert() {
        if (this.message.classList.contains("o_qclub_alert")) {
            this.message.classList.remove("alert", "alert-danger", "o_qclub_alert");
            this.message.setAttribute("role", "status");
            this.message.textContent = "";
        }
    }

    async loadAvailability() {
        this.clearAlert();
        this.clearSelection();
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
        this.availability = result;
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
            column.textContent = slot.label;
            if (slot.next_day) {
                const nextDay = document.createElement("small");
                nextDay.className = "d-block text-muted";
                nextDay.textContent = ` ${_t("(next day)")}`;
                column.append(nextDay);
            }
            row.append(column);
        }
        this.table.querySelector("thead").replaceChildren(row);
        const body = document.createDocumentFragment();
        const formatPrice = (price) => new Intl.NumberFormat(document.documentElement.lang || "en-AU", {
            style: "currency", currency: result.currency, currencyDisplay: "narrowSymbol",
            minimumFractionDigits: Number.isInteger(Number(price)) ? 0 : 2,
            maximumFractionDigits: 2,
        }).format(price);
        const labels = { free: _t("Free"), occupied: _t("Occupied"), past: _t("Past") };
        for (const table of result.tables) {
            const tableRow = document.createElement("tr");
            tableRow.className = "o_qclub_table_row";
            tableRow.dataset.tableId = String(table.id);
            const name = document.createElement("th");
            name.scope = "row";
            name.className = "o_qclub_table_heading";
            // textContent keeps names and table types inert, including HTML-like input.
            const title = document.createElement("strong");
            title.className = "d-block";
            title.textContent = table.name;
            const details = document.createElement("small");
            details.className = "d-block text-muted fw-normal";
            details.textContent = `${table.type} · ${formatPrice(table.hourly_price)} / ${_t("hour")}`;
            name.append(title, details);
            tableRow.append(name);
            for (const [index, state] of table.slots.entries()) {
                const cell = document.createElement("td");
                cell.className = `o_qclub_slot o_qclub_slot_${state}`;
                cell.dataset.tableId = String(table.id);
                cell.dataset.slotIndex = String(index);
                cell.dataset.state = state;
                cell.textContent = state === "free" ? formatPrice(table.hourly_price) :
                    state === "occupied" ? _t("Booked") : "";
                cell.setAttribute("aria-label", `${table.name}, ${result.slots[index].label}, ${labels[state]}`);
                if (state === "free") {
                    cell.setAttribute("role", "button");
                    cell.setAttribute("tabindex", "0");
                    cell.setAttribute("aria-pressed", "false");
                }
                if (state !== "free") {
                    cell.setAttribute("aria-disabled", "true");
                }
                tableRow.append(cell);
            }
            body.append(tableRow);
        }
        this.table.querySelector("tbody").replaceChildren(body);
        this.table.hidden = false;
        if (this.restore) {
            const params = this.restore;
            this.restore = null;
            if (params.has("table") && params.has("start") && params.has("hours")) {
                const tableId = Number(params.get("table"));
                const first = result.slots.findIndex((slot) => slot.start === params.get("start"));
                const hours = Number(params.get("hours"));
                const row = result.tables.find((item) => item.id === tableId);
                if (row && Number.isInteger(hours) && hours > 0 && hours <= Number(this.el.dataset.maxHours) &&
                    first >= 0 && first + hours <= result.slots.length &&
                    row.slots.slice(first, first + hours).every((state) => state === "free") &&
                    this.contiguous(first, first + hours - 1)) {
                    this.selection = { table: tableId, first, last: first + hours - 1 };
                    this.updateSelection();
                } else {
                    this.message.textContent = _t("Your selected time is no longer available.");
                }
            }
        }
    }

    clearSelection() {
        this.selection = null;
        ++this.quoteNumber;
        this.summary.hidden = true;
        this.error.textContent = "";
        this.bookButton.disabled = true;
        for (const cell of this.el.querySelectorAll(".o_qclub_slot_free")) {
            cell.setAttribute("aria-pressed", "false");
            cell.classList.remove("o_qclub_selected");
        }
    }

    contiguous(first, last) {
        const slots = this.availability.slots;
        return Date.parse(slots[last].start) - Date.parse(slots[first].start) === (last - first) * 3600000;
    }

    selectSlot(cell) {
        if (this.submitting) {
            return;
        }
        const table = Number(cell.dataset.tableId);
        const index = Number(cell.dataset.slotIndex);
        const old = this.selection;
        if (!old || old.table !== table) {
            this.selection = { table, first: index, last: index };
        } else if (index === old.first && index === old.last) {
            this.clearSelection();
            return;
        } else if (index === old.first) {
            old.first++;
        } else if (index === old.last) {
            old.last--;
        } else if (index === old.first - 1 || index === old.last + 1) {
            const first = Math.min(index, old.first);
            const last = Math.max(index, old.last);
            if (last - first + 1 > Number(this.el.dataset.maxHours) || !this.contiguous(first, last)) {
                return;
            }
            old.first = first;
            old.last = last;
        } else {
            return;
        }
        this.updateSelection();
    }

    parameters() {
        const selected = this.selection;
        return { table: selected.table, start: this.availability.slots[selected.first].start,
            hours: selected.last - selected.first + 1, date: this.dateInput.value };
    }

    async updateSelection() {
        this.clearAlert();
        const selected = this.selection;
        const number = ++this.quoteNumber;
        for (const cell of this.el.querySelectorAll(".o_qclub_slot_free")) {
            const index = Number(cell.dataset.slotIndex);
            const active = Number(cell.dataset.tableId) === selected.table &&
                index >= selected.first && index <= selected.last;
            cell.setAttribute("aria-pressed", String(active));
            cell.classList.toggle("o_qclub_selected", active);
        }
        this.summary.hidden = false;
        this.bookButton.disabled = true;
        this.error.textContent = "";
        this.el.querySelector(".o_qclub_summary").textContent = _t("Loading quote…");
        this.el.querySelector(".o_qclub_cancel_warning").hidden = true;
        try {
            const result = await this.waitFor(rpc("/billiard/booking/quote", this.parameters()));
            if (number !== this.quoteNumber) {
                return;
            }
            this.protectSyncAfterAsync(() => {
                if (result.error) {
                    this.error.textContent = result.message || _t("Please log in to view availability.");
                    return;
                }
                const money = (amount) => new Intl.NumberFormat("en-AU", {
                    style: "currency", currency: result.currency,
                }).format(amount);
                this.el.querySelector(".o_qclub_summary").textContent =
                    `${result.table_name} · ${result.table_type} | ${result.time_label} (${result.hours} hours) | ` +
                    `Table fee: ${money(result.table_fee)} | Deposit: ${money(result.deposit_amount)} ` +
                    `(${result.deposit_ratio}%). Your table is held for ${result.lock_minutes} minutes while awaiting the deposit.`;
                this.el.querySelector(".o_qclub_cancel_warning").hidden = !result.created_in_cancel_window;
                this.bookButton.textContent = this.el.dataset.public === "1" ? _t("Log in to book") : _t("Book");
                this.bookButton.disabled = false;
            })();
        } catch {
            if (!this.isDestroyed && number === this.quoteNumber) {
                this.error.textContent = _t("Quote could not be loaded. Please try again.");
            }
        }
    }

    async book() {
        if (!this.selection || this.submitting || this.bookButton.disabled) {
            return;
        }
        const params = this.parameters();
        if (this.el.dataset.public === "1") {
            const target = "/billiard/booking?" + new URLSearchParams(params).toString();
            window.location.assign("/web/login?redirect=" + encodeURIComponent(target));
            return;
        }
        this.submitting = true;
        this.bookButton.disabled = true;
        try {
            const result = await this.waitFor(rpc("/billiard/booking/submit", {
                ...params, csrf_token: this.el.dataset.csrfToken,
            }));
            if (result.confirmation_url) {
                window.location.assign(result.confirmation_url);
            } else if (result.login_url) {
                window.location.assign(result.login_url);
            } else if (result.error === "conflict") {
                await this.loadAvailability();
                this.showAlert(result.message);
            } else {
                this.error.textContent = result.message || _t("Please reload the page and try again.");
            }
        } catch {
            if (!this.isDestroyed) {
                this.error.textContent = _t("Booking could not be submitted. Please reload availability before retrying.");
            }
        } finally {
            this.submitting = false;
            if (!this.isDestroyed) {
                this.bookButton.disabled = false;
            }
        }
    }

}

registry.category("public.interactions").add("qclub_billiard.booking_grid", BookingGrid);


class BookingHold extends Interaction {
    static selector = ".o_qclub_hold";

    start() {
        const deadline = Date.now() + Number(this.el.dataset.remaining) * 1000;
        const tick = () => {
            const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
            this.el.textContent = remaining > 0 ?
                `Held for ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}` :
                _t("This hold has expired. Please make a new booking.");
        };
        tick();
        this.timer = setInterval(tick, 1000);
    }

    destroy() {
        clearInterval(this.timer);
        super.destroy();
    }
}
registry.category("public.interactions").add("qclub_billiard.booking_hold", BookingHold);
