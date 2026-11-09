import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

// Owned by BookingGrid so availability and board responses share one generation.
export class BookingBoard {
    constructor(grid) {
        this.grid = grid;
        this.el = grid.el;
        this.panel = this.el.querySelector(".o_qclub_post_panel");
        this.list = this.el.querySelector(".o_qclub_board_list");
        this.initialPost = this.el.dataset.boardPost;
        this.initialBooking = this.el.dataset.boardBooking;
        this.number = 0;
    }

    close() {
        ++this.number;
        this.panel.hidden = true;
        this.panel.replaceChildren();
    }

    reset() {
        this.close();
        this.list.replaceChildren();
    }

    node(tag, text, parent = this.panel) {
        const element = document.createElement(tag);
        if (text !== undefined) {
            element.textContent = text;
        }
        parent.append(element);
        return element;
    }

    login(post, booking) {
        const params = new URLSearchParams({ date: this.grid.dateInput.value });
        if (post) {
            params.set("post", post);
        }
        if (booking) {
            params.set("booking", booking);
        }
        return "/web/login?redirect=" + encodeURIComponent("/billiard/booking?" + params);
    }

    show() {
        this.grid.clearSelection();
        this.close();
        this.panel.hidden = false;
        this.panel.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    mark(item, action, label) {
        const start = Date.parse(item.start);
        for (const cell of this.el.querySelectorAll(".o_qclub_slot_occupied")) {
            const slot = this.grid.availability.slots[Number(cell.dataset.slotIndex)];
            const instant = Date.parse(slot.start);
            if (Number(cell.dataset.tableId) !== item.table_id || instant < start ||
                instant >= start + item.hours * 3600000) {
                continue;
            }
            cell.textContent = label;
            cell.classList.add("o_qclub_board_marker");
            cell.setAttribute("role", "button");
            cell.setAttribute("tabindex", "0");
            cell.setAttribute("aria-label", `${item.table_name}, ${slot.label}, ${label}`);
            cell.removeAttribute("aria-disabled");
            cell.onclick = action;
            cell.onkeydown = (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    action();
                }
            };
        }
    }

    async load(generation) {
        if (this.el.dataset.boardEnabled !== "1") {
            return;
        }
        const day = this.grid.dateInput.value;
        try {
            const data = await rpc("/billiard/booking/board", { date: day });
            if (this.grid.isDestroyed || generation !== this.grid.requestNumber) {
                return;
            }
            if (data.error) {
                if (data.error === "login_required") {
                    this.node("a", _t("Log in to view players wanted"), this.list).href =
                        this.login(this.initialPost, this.initialBooking);
                }
                return;
            }
            this.data = data;
            if (data.posts.length) {
                this.node("h2", _t("Players wanted on %s", data.date_label), this.list);
            }
            for (const post of data.posts) {
                const label = post.remaining ? _t("Join · %s", post.remaining) : _t("Full");
                this.mark(post, () => this.openPost(post.id), label);
                const button = this.node("button", `${post.time_label} · ${post.table_name} · ${post.display_name} · ${label}`, this.list);
                button.type = "button";
                button.className = "btn btn-outline-primary d-block mb-2";
                button.onclick = () => this.openPost(post.id);
            }
            for (const booking of data.own_bookings) {
                if (!booking.post_id) {
                    this.mark(booking, () => this.openBooking(booking), _t("Yours"));
                }
            }
            const post = this.initialPost;
            const booking = data.own_bookings.find((item) => String(item.booking_id) === this.initialBooking);
            this.initialPost = this.initialBooking = "";
            if (post) {
                await this.openPost(post, true);
            } else if (booking) {
                this.openBooking(booking);
            }
        } catch {
            // Board availability must never change the booking grid's result.
            if (!this.grid.isDestroyed && generation === this.grid.requestNumber) {
                this.node("p", _t("Players wanted could not be loaded. Please try again."), this.list);
            }
        }
    }

    async openPost(id, restoreDate = false) {
        this.show();
        const number = this.number;
        this.node("p", _t("Loading post…"));
        try {
            const post = await rpc("/billiard/booking/post", { post: id });
            if (this.grid.isDestroyed || number !== this.number) {
                return;
            }
            this.panel.replaceChildren();
            if (post.error) {
                this.node("p", post.message || _t("Please log in to view this post."));
                if (post.error === "login_required") {
                    this.node("a", _t("Log in")).href = this.login(id);
                }
                return;
            }
            if (restoreDate && post.date !== this.grid.dateInput.value) {
                this.initialPost = String(id);
                this.grid.dateInput.value = post.date;
                await this.grid.loadAvailability();
                return;
            }
            this.node("h2", post.display_name);
            this.node("p", `${post.table_name} · ${post.time_label}`);
            this.node("p", _t("Level: %(level)s · Players wanted: %(players)s", { level: post.level[0].toUpperCase() + post.level.slice(1), players: post.remaining }));
            this.node("p", post.message).className = "o_qclub_post_message text-break";
            if (post.state === "closed") {
                // Refresh stale markers, while keeping the closed panel visible.
                const refreshing = this.grid.loadAvailability();
                const refreshNumber = this.number;
                await refreshing;
                if (this.grid.isDestroyed || refreshNumber !== this.number) {
                    return;
                }
                this.show();
                this.node("h2", post.display_name);
                this.node("p", `${post.table_name} · ${post.time_label}`);
                this.node("p", _t("Level: %(level)s · Players wanted: %(players)s", { level: post.level[0].toUpperCase() + post.level.slice(1), players: post.remaining }));
                this.node("p", post.message).className = "o_qclub_post_message text-break";
                this.node("p", _t("This post is closed."));
            } else if (this.el.dataset.public === "1") {
                this.node("a", _t("Log in to find players")).href = this.login(id);
            }
        } catch {
            if (!this.grid.isDestroyed && number === this.number) {
                this.panel.replaceChildren();
                this.node("p", _t("This post could not be loaded. Please try again."));
            }
        }
    }

    openBooking(booking) {
        if (booking.post_id) {
            this.openPost(booking.post_id);
            return;
        }
        this.show();
        this.node("h2", booking.state === "confirmed" ? _t("Find players") : _t("Your booking"));
        this.node("p", `${booking.table_name} · ${booking.time_label}`);
        if (booking.state !== "confirmed") {
            this.node("p", _t("Your booking must be confirmed before you can find players."));
            return;
        }
        const form = this.node("form");
        const field = (tag, text, name) => {
            // Link by id: a <select> nested in its label takes the options into its accessible name.
            const label = this.node("label", text, form);
            label.className = "d-block mb-1";
            label.htmlFor = `o_qclub_post_${name}`;
            const input = this.node(tag, undefined, form);
            input.id = label.htmlFor;
            input.name = name;
            input.className = "form-control mb-2";
            return input;
        };
        const message = field("textarea", _t("Message (Don't share personal contact details)"), "message");
        message.required = true;
        message.maxLength = 500;
        // Buttons rather than a native <select>: Chrome clipped the native list on some displays.
        const levels = this.node("fieldset", undefined, form);
        levels.className = "mb-2";
        this.node("legend", _t("Level"), levels).className = "fs-6 mb-1";
        const group = this.node("div", undefined, levels);
        group.className = "btn-group flex-wrap";
        const levelLabels = {
            any: _t("Any"), beginner: _t("Beginner"), intermediate: _t("Intermediate"), advanced: _t("Advanced"),
        };
        for (const [value, text] of Object.entries(levelLabels)) {
            const option = this.node("input", undefined, group);
            option.type = "radio";
            option.name = "level";
            option.value = value;
            option.id = `o_qclub_post_level_${value}`;
            option.className = "btn-check";
            option.checked = value === "any";
            const optionLabel = this.node("label", text, group);
            optionLabel.htmlFor = option.id;
            optionLabel.className = "btn btn-outline-primary";
        }
        const players = field("input", _t("Players wanted"), "players_needed");
        players.type = "number";
        players.min = "1";
        players.max = String(this.data.max_players);
        players.value = "1";
        players.required = true;
        let terms;
        if (!this.data.terms_accepted) {
            this.node("p", this.data.terms, form).className = "o_qclub_terms";
            const label = this.node("label", _t("I agree to the Community Guidelines"), form);
            terms = this.node("input", undefined, label);
            terms.type = "checkbox";
            terms.name = "accept_terms";
            terms.required = true;
        }
        const error = this.node("p", "", form);
        error.setAttribute("role", "alert");
        const submit = this.node("button", _t("Find players"), form);
        submit.type = "submit";
        submit.className = "btn btn-primary d-block mt-2";
        form.onsubmit = async (event) => {
            event.preventDefault();
            submit.disabled = true;
            const number = this.number;
            try {
                const result = await rpc("/billiard/booking/post/create", {
                    booking_id: booking.booking_id, message: message.value, level: form.elements.level.value,
                    players_needed: Number(players.value), accept_terms: Boolean(terms?.checked),
                    csrf_token: this.el.dataset.csrfToken, date: this.grid.dateInput.value,
                });
                if (this.grid.isDestroyed || number !== this.number) {
                    return;
                }
                if (result.login_url) {
                    window.location.assign(result.login_url);
                } else if (result.error) {
                    error.textContent = result.message;
                } else {
                    const refreshing = this.grid.loadAvailability();
                    const refreshNumber = this.number;
                    await refreshing;
                    if (!this.grid.isDestroyed && refreshNumber === this.number) {
                        await this.openPost(result.id);
                    }
                }
            } catch {
                if (!this.grid.isDestroyed && number === this.number) {
                    error.textContent = _t("Post could not be submitted. Please try again.");
                }
            } finally {
                submit.disabled = false;
            }
        };
    }
}
