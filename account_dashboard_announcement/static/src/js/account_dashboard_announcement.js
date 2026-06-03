/** @odoo-module **/

import { onMounted, onPatched, useState } from "@odoo/owl";
import { DashboardKanbanRenderer } from "@account/views/account_dashboard_kanban/account_dashboard_kanban_renderer";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

const DISMISSED_KEY_PREFIX = "account_dashboard_announcement.dismissed.";
const STYLE_TYPES = new Set(["info", "warning", "success", "danger"]);

patch(DashboardKanbanRenderer.prototype, {
    setup() {
        super.setup();
        this.announcementOrm = useService("orm");
        this.announcementState = useState({
            announcement: false,
        });

        onMounted(async () => {
            this.renderDashboardAnnouncement();
            await this.loadDashboardAnnouncement();
        });
        onPatched(() => this.renderDashboardAnnouncement());
    },

    async loadDashboardAnnouncement() {
        try {
            const announcement = await this.announcementOrm.call(
                "account.dashboard.announcement",
                "get_active_announcement",
                []
            );
            this.announcementState.announcement = announcement || false;
            this.renderDashboardAnnouncement();
        } catch (error) {
            browser.console.warn("Could not load the Accounting dashboard announcement.", error);
            this.announcementState.announcement = false;
            this.renderDashboardAnnouncement();
        }
    },

    renderDashboardAnnouncement() {
        const root = this.rootRef?.el;
        if (!root) {
            return;
        }

        const existingBanner = root.querySelector(
            ":scope > .o_account_dashboard_announcement_banner"
        );
        const announcement = this.announcementState.announcement;
        if (!announcement || this.isDashboardAnnouncementDismissed(announcement.id)) {
            existingBanner?.remove();
            return;
        }

        const banner = existingBanner || document.createElement("section");
        const styleType = STYLE_TYPES.has(announcement.style_type)
            ? announcement.style_type
            : "info";

        banner.className = [
            "o_account_dashboard_announcement_banner",
            `o_account_dashboard_announcement_${styleType}`,
        ].join(" ");
        banner.dataset.announcementId = announcement.id;
        banner.setAttribute("role", "status");
        banner.replaceChildren();

        const content = document.createElement("div");
        content.className = "o_account_dashboard_announcement_content";

        const title = document.createElement("strong");
        title.className = "o_account_dashboard_announcement_title";
        title.textContent = announcement.name;

        const message = document.createElement("span");
        message.className = "o_account_dashboard_announcement_message";
        message.textContent = announcement.message;

        content.append(title, message);
        banner.append(content);

        if (announcement.dismissible) {
            const closeButton = document.createElement("button");
            closeButton.type = "button";
            closeButton.className = "o_account_dashboard_announcement_close";
            closeButton.setAttribute("aria-label", "Dismiss announcement");
            closeButton.title = "Dismiss";
            closeButton.textContent = "\u00d7";
            closeButton.addEventListener("click", () => {
                this.dismissDashboardAnnouncement(announcement.id);
            });
            banner.append(closeButton);
        }

        if (!existingBanner) {
            root.prepend(banner);
        }
    },

    dismissDashboardAnnouncement(announcementId) {
        browser.localStorage.setItem(`${DISMISSED_KEY_PREFIX}${announcementId}`, "1");
        this.renderDashboardAnnouncement();
    },

    isDashboardAnnouncementDismissed(announcementId) {
        return browser.localStorage.getItem(`${DISMISSED_KEY_PREFIX}${announcementId}`) === "1";
    },
});
