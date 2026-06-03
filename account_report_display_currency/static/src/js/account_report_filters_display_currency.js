/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";

patch(AccountReportFilters.prototype, {
    get selectedDisplayCurrencyName() {
        return this.controller.cachedFilterOptions.display_currency_name;
    },

    get displayCurrencyButtonLabel() {
        return "In " + this.selectedDisplayCurrencyName;
    },
});
