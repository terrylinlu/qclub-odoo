import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const CANCEL_NOTICE_KEY = "qclub.booking.cancelled";

function showCancellationNotice() {
    const wrap = document.querySelector("#wrap");
    if (!wrap) {
        return;
    }
    try {
        if (!window.sessionStorage.getItem(CANCEL_NOTICE_KEY)) {
            return;
        }
        window.sessionStorage.removeItem(CANCEL_NOTICE_KEY);
    } catch {
        return;
    }
    const notice = document.createElement("div");
    notice.className = "alert alert-success alert-dismissible o_qclub_cancel_notice";
    notice.setAttribute("role", "alert");
    notice.textContent = "Booking cancelled.";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close";
    close.setAttribute("aria-label", "Close");
    close.onclick = () => notice.remove();
    notice.append(close);
    wrap.prepend(notice);
}

// A cancelled booking may leave the page without any cancellation buttons.
class CancellationNotice extends Interaction {
    static selector = "#wrap";

    start() {
        showCancellationNotice();
    }
}
registry.category("public.interactions").add("qclub_billiard.cancellation_notice", CancellationNotice);

export class CancelBooking extends Interaction {
    static selector = ".o_qclub_cancel";
    dynamicContent = { _root: { "t-on-click": () => this.open() } };

    start() {
        showCancellationNotice();
    }

    async open() {
        if (this.busy) {
            return;
        }
        this.busy = true;
        const route = `/billiard/booking/${this.el.dataset.bookingId}/cancel`;
        let dialog;
        try {
            const outcome = await rpc(`${route}/outcome`, {});
            dialog = document.createElement("dialog");
            dialog.setAttribute("aria-label", "Cancel booking");
            const text = document.createElement("p");
            text.textContent = outcome.text;
            const confirm = document.createElement("button");
            confirm.type = "button";
            confirm.className = "btn btn-danger";
            confirm.textContent = "Confirm cancellation";
            const keep = document.createElement("button");
            keep.type = "button";
            keep.className = "btn btn-secondary ms-2";
            keep.textContent = "Keep booking";
            keep.onclick = () => dialog.close();
            confirm.onclick = async () => {
                confirm.disabled = true;
                keep.disabled = true;
                try {
                    await rpc(`${route}/confirm`, { csrf_token: this.el.dataset.csrfToken });
                    try {
                        window.sessionStorage.setItem(CANCEL_NOTICE_KEY, "1");
                    } catch {
                        // Storage can be unavailable in private browsing.
                    }
                    window.location.reload();
                } catch (error) {
                    text.textContent = error.data?.message || "Cancellation failed. Please reload and try again.";
                    confirm.disabled = false;
                    keep.disabled = false;
                }
            };
            dialog.append(text, confirm, keep);
            dialog.addEventListener("close", () => { dialog.remove(); this.busy = false; });
            document.body.append(dialog);
            dialog.showModal();
        } catch (error) {
            dialog?.remove();
            this.busy = false;
            window.alert(error.data?.message || "Please reload the page and try again.");
        }
    }
}
registry.category("public.interactions").add("qclub_billiard.cancel_booking", CancelBooking);
