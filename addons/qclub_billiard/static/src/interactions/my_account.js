import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class MyAccount extends Interaction {
    static selector = ".o_qclub_my_account";

    dynamicContent = {
        '[role="tab"]': {
            "t-on-click": (event) => this.activate(event.currentTarget, true),
            "t-on-keydown": (event) => {
                if (!["ArrowLeft", "ArrowRight"].includes(event.key)) {
                    return;
                }
                event.preventDefault();
                const index = this.tabs.indexOf(event.currentTarget);
                const next = this.tabs[(index + (event.key === "ArrowRight" ? 1 : -1) + this.tabs.length) % this.tabs.length];
                this.activate(next, true);
                next.focus();
            },
        },
    };

    start() {
        this.tabs = [...this.el.querySelectorAll('[role="tab"]')];
        this.restoreTab = () => this.activate(
            this.tabs.find((tab) => `#${tab.dataset.tab}` === window.location.hash) || this.tabs[0]
        );
        this.restoreTab();
        window.addEventListener("hashchange", this.restoreTab);
        window.addEventListener("popstate", this.restoreTab);
    }

    destroy() {
        window.removeEventListener("hashchange", this.restoreTab);
        window.removeEventListener("popstate", this.restoreTab);
        super.destroy();
    }

    activate(selected, remember = false) {
        for (const tab of this.tabs) {
            const active = tab === selected;
            tab.classList.toggle("active", active);
            tab.setAttribute("aria-selected", String(active));
            tab.tabIndex = active ? 0 : -1;
            const pane = this.el.querySelector(`#${tab.getAttribute("aria-controls")}`);
            pane.classList.toggle("active", active);
            pane.classList.toggle("show", active);
        }
        if (remember) {
            const url = new URL(window.location.href);
            url.hash = selected.dataset.tab;
            window.history.replaceState(window.history.state, "", url);
        }
    }
}

registry.category("public.interactions").add("qclub_billiard.my_account", MyAccount);
