from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.tools import SQL
from odoo.addons.payment.controllers.portal import PaymentPortal

from .my_account import BilliardAccount


# Keep one booking-controller leaf: Booking -> Board -> Account -> Payment.
# Odoo must not choose among sibling leaves for inherited booking routes.
class BilliardPayment(BilliardAccount, PaymentPortal):
    def _get_booking_payment_values(self, booking):
        partner, currency = booking.partner_id, booking.currency_id
        report = {}
        providers = request.env['payment.provider'].sudo()._get_compatible_providers(
            booking.company_id.id, partner.id, booking.deposit_amount,
            currency_id=currency.id, website_id=booking.website_id.id, report=report,
        )
        methods = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers.ids, partner.id, currency_id=currency.id, report=report,
        )
        tokens = request.env['payment.token'].sudo()._get_available_tokens(providers.ids, partner.id)
        return {
            'company_mismatch': not self._can_partner_pay_in_company(partner, booking.company_id),
            'expected_company': booking.company_id, 'res_company': booking.company_id, 'amount': booking.deposit_amount,
            'currency': currency, 'partner_id': partner.id, 'providers_sudo': providers,
            'payment_methods_sudo': methods, 'tokens_sudo': tokens, 'availability_report': report,
            'show_tokenize_input_mapping': self._compute_show_tokenize_input_mapping(providers),
            'transaction_route': f'/billiard/booking/{booking.id}/transaction',
            'landing_route': '/billiard/booking/confirmation/' + booking.name,
            **self._get_extra_payment_form_values(),
        }

    @http.route()
    def confirmation(self, name, **kwargs):
        response = super().confirmation(name, **kwargs)
        booking = response.qcontext['booking']
        response.qcontext['show_deposit_form'] = booking._can_pay_deposit()
        if response.qcontext['show_deposit_form']:
            response.qcontext.update(self._get_booking_payment_values(booking))
        return response

    @http.route('/billiard/booking/<int:booking_id>/transaction', type='jsonrpc', auth='user',
                website=True, methods=['POST'])
    def booking_transaction(self, booking_id, **kwargs):
        self._website_config()
        self._validate_transaction_kwargs(kwargs, additional_allowed_keys=('currency_id', 'partner_id', 'access_token'))
        booking = request.env['qclub.booking'].sudo().search([
            ('id', '=', booking_id), ('website_id', '=', request.website.id),
            ('partner_id', '=', request.env.user.partner_id.id),
        ], limit=1)
        if not booking:
            raise ValidationError(_('This booking cannot accept a deposit.'))
        booking._lock_tables(booking.table_id.ids)
        request.env.cr.execute(SQL('SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE', booking.id))
        booking.invalidate_recordset()
        if not booking._can_pay_deposit():
            raise ValidationError(_('This booking cannot accept a deposit.'))
        values = self._get_booking_payment_values(booking)
        if values['company_mismatch']:
            raise ValidationError(_('The customer cannot pay in this company.'))
        provider_id = kwargs.get('provider_id')
        if provider_id not in values['providers_sudo'].ids:
            raise ValidationError(_('This payment provider is unavailable on this website.'))
        if kwargs.get('flow') == 'token':
            token = values['tokens_sudo'].filtered(lambda t: t.id == kwargs.get('token_id'))
            if not token or token.provider_id.id != provider_id:
                raise ValidationError(_('This payment token is unavailable.'))
        elif kwargs.get('flow') in ('direct', 'redirect'):
            method = values['payment_methods_sudo'].filtered(lambda m: m.id == kwargs.get('payment_method_id'))
            if not method or provider_id not in method.provider_ids.ids:
                raise ValidationError(_('This payment method is unavailable.'))
        else:
            raise ValidationError(_('Invalid payment flow.'))
        booking._extend_payment_lock()
        kwargs.update({
            'amount': booking.deposit_amount, 'currency_id': booking.currency_id.id,
            'partner_id': booking.partner_id.id, 'landing_route': values['landing_route'],
            'is_validation': False,
        })
        kwargs.pop('csrf_token', None)
        kwargs.pop('access_token', None)
        tx = self._create_transaction(custom_create_values={
            'qclub_booking_id': booking.id, 'website_id': booking.website_id.id,
        }, **kwargs)
        return tx._get_processing_values()
