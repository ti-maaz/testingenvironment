import { BankRecButtonList } from "@account_accountant/components/bank_reconciliation/button_list/button_list";
import { patch } from "@web/core/utils/patch";

patch(BankRecButtonList.prototype, {
    async openRecodeWizard() {
        const action = await this.orm.call("account.bank.statement.line", "action_open_recode_wizard", [
            [this.statementLineData.id],
        ]);
        if (action) {
            return this.action.doAction(action);
        }
    },
});
