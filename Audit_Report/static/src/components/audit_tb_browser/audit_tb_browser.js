/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

import {
    Component,
    onWillStart,
    onWillUpdateProps,
    useRef,
    useState,
    useSubEnv,
} from "@odoo/owl";

import { AccountReportController } from "@account_reports/components/account_report/controller";
import { AccountReportButtonsBar } from "@account_reports/components/account_report/buttons_bar/buttons_bar";
import { AccountReportCogMenu } from "@account_reports/components/account_report/cog_menu/cog_menu";
import { AccountReportEllipsis } from "@account_reports/components/account_report/ellipsis/ellipsis";
import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { AccountReportHeader } from "@account_reports/components/account_report/header/header";
import { AccountReportLine } from "@account_reports/components/account_report/line/line";
import { AccountReportLineCell } from "@account_reports/components/account_report/line_cell/line_cell";
import { AccountReportLineName } from "@account_reports/components/account_report/line_name/line_name";
import { AccountReportSearchBar } from "@account_reports/components/account_report/search_bar/search_bar";
import { AccountReportChatter } from "@account_reports/components/mail/chatter";

class EmbeddedAuditTbReportController extends AccountReportController {
    constructor(action, owner) {
        super(action);
        this.owner = owner;
    }

    sessionOptionsID() {
        return `audit.report.tb:${this.owner.recordId}:${this.owner.activePeriod}:${user.defaultCompany.id}`;
    }

    async buttonAction(ev, button) {
        if (button.action === "action_import_audit_tb_overrides") {
            ev?.preventDefault();
            ev?.stopPropagation();
            await this.owner.applyCurrentOptions();
            return;
        }
        if (button.action === "action_back_to_audit_tb_override") {
            ev?.preventDefault();
            ev?.stopPropagation();
            return;
        }
        return super.buttonAction(ev, button);
    }
}

export class AuditTbBrowser extends Component {
    static template = "Audit_Report.AuditTbBrowser";
    static props = {
        ...standardWidgetProps,
        record: { type: Object, optional: true },
        list: { type: Object, optional: true },
    };
    static components = {
        ControlPanel,
        AccountReportButtonsBar,
        AccountReportCogMenu,
        AccountReportSearchBar,
        AccountReportChatter,
    };

    static customizableComponents = [
        AccountReportEllipsis,
        AccountReportFilters,
        AccountReportHeader,
        AccountReportLine,
        AccountReportLineCell,
        AccountReportLineName,
    ];
    static defaultComponentsMap = [];

    setup() {
        this.rootRef = useRef("root");
        this.env.config.viewSwitcherEntries = [];
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.ui = useService("ui");

        for (const customizableComponent of AuditTbBrowser.customizableComponents) {
            AuditTbBrowser.defaultComponentsMap[customizableComponent.name] = customizableComponent;
        }

        this.state = useState({
            activePeriod: this.props.record?.data.tb_browser_active_period || "current",
            loading: true,
            reportLoaded: false,
            emptyMessage: "",
        });

        this.controller = useState(
            new EmbeddedAuditTbReportController(
                { context: {}, params: { options: {} }, keep_journal_groups_options: true },
                this
            )
        );
        this.initialQuery = null;
        this.baseReportId = null;
        this.baseContext = {};
        this.lastWizardStateSignature = this._wizardStateSignature(this.props);

        useSubEnv({
            controller: this.controller,
            component: this.getComponent.bind(this),
            template: this.getTemplate.bind(this),
        });

        onWillStart(async () => {
            await this.loadPeriod(this.state.activePeriod);
        });

        onWillUpdateProps(async (nextProps) => {
            const nextSignature = this._wizardStateSignature(nextProps);
            const nextActivePeriod =
                this.state.activePeriod === "prior" && !this._showPriorPeriodForData(this._recordData(nextProps))
                    ? "current"
                    : this.state.activePeriod;

            if (nextSignature === this.lastWizardStateSignature && nextActivePeriod === this.state.activePeriod) {
                return;
            }

            this.lastWizardStateSignature = nextSignature;
            await this.loadPeriod(nextActivePeriod, nextProps);
        });
    }

    get recordId() {
        return this._recordId(this.props);
    }

    get activePeriod() {
        return this.state.activePeriod;
    }

    get applyButtonLabel() {
        return this.state.activePeriod === "prior"
            ? _t("Apply to Prior Overrides")
            : _t("Apply to Current Overrides");
    }

    get showPriorPeriod() {
        return this._showPriorPeriodForData(this._recordData(this.props));
    }

    _recordData(props = this.props) {
        return props.record?.data || {};
    }

    _recordId(props = this.props) {
        return props.record?.resId || props.record?.data.id || false;
    }

    _companyId(props = this.props) {
        const companyValue = this._recordData(props).company_id;
        if (Array.isArray(companyValue)) {
            return companyValue[0] || false;
        }
        if (companyValue && typeof companyValue === "object") {
            return companyValue.resId || companyValue.id || false;
        }
        return companyValue || false;
    }

    _showPriorPeriodForData(data) {
        const category = (data.audit_period_category || "").toLowerCase();
        return category.endsWith("_2y");
    }

    _wizardStatePayload(props = this.props) {
        const data = this._recordData(props);
        return {
            audit_period_category: data.audit_period_category || false,
            date_start: data.date_start || false,
            date_end: data.date_end || false,
            prior_year_mode: data.prior_year_mode || false,
            prior_date_start: data.prior_date_start || false,
            prior_date_end: data.prior_date_end || false,
        };
    }

    _wizardStateSignature(props = this.props) {
        return JSON.stringify({
            record_id: this._recordId(props),
            company_id: this._companyId(props),
            ...this._wizardStatePayload(props),
        });
    }

    _hasRequiredDates(periodKey, props = this.props) {
        const data = this._recordData(props);
        if (periodKey === "prior") {
            if (!this._showPriorPeriodForData(data)) {
                return false;
            }
            if ((data.prior_year_mode || "auto") === "manual") {
                return Boolean(data.prior_date_start && data.prior_date_end);
            }
        }
        return Boolean(data.date_end);
    }

    get cssCustomClass() {
        return this.controller.options?.custom_display_config?.css_custom_class || "";
    }

    getComponent(name) {
        const customComponents = this.controller.options?.custom_display_config?.components;
        if (customComponents && customComponents[name]) {
            return registry.category("account_reports_custom_components").get(customComponents[name]);
        }
        return AuditTbBrowser.defaultComponentsMap[name];
    }

    getTemplate(name) {
        const customTemplates = this.controller.options?.custom_display_config?.templates;
        if (customTemplates && customTemplates[name]) {
            return customTemplates[name];
        }
        return `account_reports.${name}Customizable`;
    }

    get tableClasses() {
        let classes = "";
        if ((this.controller.options?.columns || []).length > 1) {
            classes += " striped";
        }
        if (this.controller.options?.horizontal_split) {
            classes += " w-50 mx-2";
        }
        return classes;
    }

    _optionsFieldName(periodKey) {
        return periodKey === "prior" ? "tb_prior_report_options_json" : "tb_current_report_options_json";
    }

    _sessionOptionsKey(periodKey, props = this.props) {
        const recordId = this._recordId(props) || `draft:${this._companyId(props) || "new"}`;
        return `audit.report.tb:${recordId}:${periodKey}:${user.defaultCompany.id}`;
    }

    _getSessionOptions(periodKey, props = this.props) {
        try {
            return JSON.parse(browser.sessionStorage.getItem(this._sessionOptionsKey(periodKey, props)));
        } catch {
            return null;
        }
    }

    _setSessionOptions(periodKey, options, props = this.props) {
        if (!options) {
            return;
        }
        browser.sessionStorage.setItem(
            this._sessionOptionsKey(periodKey, props),
            JSON.stringify(options)
        );
    }

    _parseStoredOptions(periodKey, props = this.props) {
        const fieldName = this._optionsFieldName(periodKey);
        const rawValue = props.record?.data[fieldName];
        if (!rawValue) {
            return null;
        }
        try {
            const parsed = JSON.parse(rawValue);
            return parsed && typeof parsed === "object" ? parsed : null;
        } catch {
            return null;
        }
    }

    _hasUsableOptions(options) {
        return Boolean(options?.date?.date_to);
    }

    _buildActionConfig(periodKey, options) {
        return {
            context: {
                ...(this.baseContext || {}),
                audit_tb_override_period_key: periodKey,
                audit_tb_embedded: true,
            },
            params: {
                options,
                ignore_session: true,
            },
            keep_journal_groups_options: true,
        };
    }

    async _cacheOptionsForPeriod(periodKey, options, props = this.props) {
        this._setSessionOptions(periodKey, options, props);
    }

    async loadPeriod(periodKey, props = this.props) {
        const recordId = this._recordId(props);
        const companyId = this._companyId(props);

        this.state.loading = true;
        this.state.emptyMessage = "";

        if (!recordId && !companyId) {
            this.state.loading = false;
            this.state.reportLoaded = false;
            this.state.emptyMessage = _t("Select a company to load the embedded Trial Balance.");
            return;
        }

        if (!this._hasRequiredDates(periodKey, props)) {
            this.state.activePeriod = periodKey;
            this.state.loading = false;
            this.state.reportLoaded = false;
            this.state.emptyMessage = _t("Set the report dates to load the embedded Trial Balance.");
            return;
        }

        const storedOptions = this._getSessionOptions(periodKey, props) || this._parseStoredOptions(periodKey, props);
        const configMethod = recordId ? "get_tb_browser_config" : "get_tb_browser_preview_config";
        const configArgs = recordId
            ? [[recordId], periodKey, this._hasUsableOptions(storedOptions) ? storedOptions : false, this._wizardStatePayload(props)]
            : [companyId, periodKey, this._hasUsableOptions(storedOptions) ? storedOptions : false, this._wizardStatePayload(props)];
        const config = await this.orm.call(
            "audit.report",
            configMethod,
            configArgs
        );
        if (config?.missing_dates) {
            this.baseReportId = config.report_id;
            this.baseContext = config.context || {};
            this.state.activePeriod = periodKey;
            this.state.loading = false;
            this.state.reportLoaded = false;
            this.state.emptyMessage = config.message || _t("Set the report dates to load the embedded Trial Balance.");
            return;
        }
        this.baseReportId = config.report_id;
        this.baseContext = config.context || {};
        await this._cacheOptionsForPeriod(periodKey, config.options, props);

        this.state.activePeriod = periodKey;
        this.controller.action = this._buildActionConfig(periodKey, config.options);
        await this.controller.load(this.env);
        this.state.loading = false;
        this.state.reportLoaded = true;
    }

    async switchPeriod(periodKey) {
        if (periodKey === this.state.activePeriod || this.state.loading) {
            return;
        }
        if (this.controller.cachedFilterOptions) {
            await this._cacheOptionsForPeriod(this.state.activePeriod, this.controller.cachedFilterOptions);
        }
        await this.loadPeriod(periodKey);
    }

    async applyCurrentOptions() {
        if (this.state.loading || !this.controller.cachedFilterOptions) {
            return;
        }
        await this._cacheOptionsForPeriod(this.state.activePeriod, this.controller.cachedFilterOptions);
        await this.props.record.save({ reload: false });
        if (!this.recordId) {
            this.notification.add(_t("Save the wizard to apply Trial Balance overrides."), {
                type: "warning",
            });
            return;
        }
        const result = await this.orm.call(
            "audit.report",
            "apply_tb_browser_options",
            [[this.recordId], this.state.activePeriod, this.controller.cachedFilterOptions]
        );
        if (result?.server_values && this.props.record?._applyValues) {
            this.props.record._applyValues(result.server_values);
        }
        this.notification.add(
            _t("%(label)s overrides updated from Odoo Trial Balance (%(count)s lines).", {
                label: this.state.activePeriod === "prior" ? _t("Prior") : _t("Current"),
                count: result?.line_count || 0,
            }),
            { type: "success" }
        );
    }

    onKeydown(ev) {
        if (ev.key === "Escape") {
            this.controller.closeChatter();
        }
    }
}

export const auditTbBrowserWidget = {
    component: AuditTbBrowser,
    fieldDependencies: [
        { name: "tb_browser_active_period", type: "selection" },
        { name: "tb_current_report_options_json", type: "text" },
        { name: "tb_prior_report_options_json", type: "text" },
        { name: "audit_period_category", type: "selection" },
        { name: "date_start", type: "date" },
        { name: "date_end", type: "date" },
        { name: "prior_year_mode", type: "selection" },
        { name: "prior_date_start", type: "date" },
        { name: "prior_date_end", type: "date" },
        { name: "company_id", type: "many2one" },
    ],
};

registry.category("view_widgets").add("audit_tb_browser", auditTbBrowserWidget);
