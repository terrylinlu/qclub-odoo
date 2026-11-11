"""Scope commerce documents only on websites offering online billiard booking."""
from odoo.addons.account.controllers.portal import PortalAccount
from odoo.addons.sale.controllers.portal import CustomerPortal
from odoo.fields import Domain
from odoo.http import request


def company_domain(domain):
    website = getattr(request, "website", None)
    if website and request.env["qclub.config"].sudo().search_count([
        ("website_id", "=", website.id), ("online_booking", "=", True),
    ]):
        return Domain(domain) & Domain("company_id", "=", website.company_id.id)
    return domain


class BilliardSalePortal(CustomerPortal):
    def _prepare_quotations_domain(self, partner):
        return company_domain(super()._prepare_quotations_domain(partner))

    def _prepare_orders_domain(self, partner):
        return company_domain(super()._prepare_orders_domain(partner))


class BilliardInvoicePortal(PortalAccount):
    def _get_invoices_domain(self, m_type=None):
        return company_domain(super()._get_invoices_domain(m_type=m_type))

    def _get_overdue_invoices_domain(self, partner_id=None):
        return company_domain(super()._get_overdue_invoices_domain(partner_id=partner_id))
