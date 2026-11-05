{
    "name": "Q Club Billiard Booking",
    "version": "19.0.1.1.0",
    "summary": "台球厅在线预约：桌台、时段预约、押金、约球留言板",
    "category": "Website",
    "author": "Q Club",
    "license": "LGPL-3",
    "depends": ["website_sale", "portal", "bus", "mail"],
    "data": [
        "security/qclub_security.xml",
        "security/ir.model.access.csv",
        "views/qclub_table_views.xml",
        "views/qclub_config_views.xml",
        "views/qclub_menus.xml",
    ],
    "installable": True,
    "application": True,
}
