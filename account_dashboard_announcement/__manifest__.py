{
    "name": "Account Dashboard Announcement",
    "version": "19.0.1.0.0",
    "summary": "Show a global announcement banner on the Accounting dashboard.",
    "category": "Accounting",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/account_dashboard_announcement_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "account_dashboard_announcement/static/src/js/account_dashboard_announcement.js",
            "account_dashboard_announcement/static/src/scss/account_dashboard_announcement.scss",
        ],
    },
    "installable": True,
    "application": False,
}
