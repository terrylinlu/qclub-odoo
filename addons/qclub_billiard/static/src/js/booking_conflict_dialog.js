/** @odoo-module **/

import { registry } from "@web/core/registry";
import { WarningDialog, odooExceptionTitleMap } from "@web/core/errors/error_dialogs";

const exceptionName = "odoo.addons.qclub_billiard.models.qclub_booking.BookingConflict";
odooExceptionTitleMap.set(exceptionName, odooExceptionTitleMap.get("odoo.exceptions.ValidationError"));
registry.category("error_dialogs").add(exceptionName, WarningDialog);
