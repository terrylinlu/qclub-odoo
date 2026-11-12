#!/usr/bin/env bash
# Local qclub_demo only. Never trace this script or print container environment.
set +x
set -euo pipefail
cd "$(dirname "$0")/.."
readonly demo_db="${QCLUB_DEMO_DB:-qclub_demo}"
[[ "$demo_db" == qclub_demo ]] || { echo 'REFUSED: only qclub_demo is allowed.' >&2; exit 1; }
compose=(docker compose -f docker/docker-compose.test.yml)
readonly forwarder=qclub-stripe-demo
case "${1:-start}" in
  status)
    docker ps -a --filter "name=^/${forwarder}$" --format '{{.Names}}: {{.Status}}'
    exit 0 ;;
  stop)
    docker rm -f "$forwarder" >/dev/null 2>&1 || true
    echo 'Stripe demo forwarding stopped. Run make demo to restore Demo after disabling Q Club Stripe.'
    exit 0 ;;
  start) ;;
  *) echo 'Usage: tools/stripe_demo.sh [start|stop|status]' >&2; exit 2 ;;
esac
# Source private files on the host; pass environment NAMES, never values or mounts.
for config_file in "$HOME/.config/qclub/stripe-test.env" "$HOME/.config/qclub/stripe-webhook.env"; do
  [[ -f "$config_file" && "$(stat -c '%a' "$config_file")" == 600 ]] || {
    echo 'Required Stripe environment files must exist with mode 600.' >&2; exit 1;
  }
  set -a
  . "$config_file"
  set +a
done
# Expected names: STRIPE_TEST_PUBLISHABLE_KEY, STRIPE_TEST_SECRET_KEY, STRIPE_WEBHOOK_SECRET.
[[ -n "${STRIPE_TEST_PUBLISHABLE_KEY:-}" && -n "${STRIPE_TEST_SECRET_KEY:-}" && -n "${STRIPE_WEBHOOK_SECRET:-}" ]] || {
  echo 'Missing Stripe test environment variables.' >&2; exit 1;
}
# Validate before installing anything. Output contains only a generic result.
python3 - <<'PY'
import os
import re
for name, prefix in [('STRIPE_TEST_PUBLISHABLE_KEY', 'pk_test_'), ('STRIPE_TEST_SECRET_KEY', 'sk_test_'),
                     ('STRIPE_WEBHOOK_SECRET', 'whsec_')]:
    value = os.environ.get(name, '')
    if '_live_' in value or not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9_]+', value):
        raise SystemExit('REFUSED: only well-formed Stripe test credentials are accepted.')
PY
"${compose[@]}" run --rm -T --no-deps demo odoo -d "$demo_db" -i payment_stripe \
  --stop-after-init --no-http --without-demo=True --log-level=error >/dev/null 2>&1
"${compose[@]}" run --rm -T --no-deps \
  -e STRIPE_TEST_PUBLISHABLE_KEY -e STRIPE_TEST_SECRET_KEY -e STRIPE_WEBHOOK_SECRET \
  demo odoo shell -d "$demo_db" --no-http --log-level=error >/dev/null 2>&1 <<'PY'
import os
if env.cr.dbname != 'qclub_demo':
    raise SystemExit('REFUSED: only qclub_demo is allowed.')
website = env['website'].search([('name', '=', 'Q Club')], limit=1)
if not website:
    raise SystemExit('Q Club website is missing.')
config = env['qclub.config']._get_for_website(website)
config._configure_stripe_test(os.environ['STRIPE_TEST_PUBLISHABLE_KEY'], os.environ['STRIPE_TEST_SECRET_KEY'],
                              os.environ['STRIPE_WEBHOOK_SECRET'])
env['payment.provider'].search([('code', '=', 'demo'), ('website_id', '=', website.id),
                                ('company_id', '=', website.company_id.id)]).write({'state': 'disabled'})
env.cr.commit()
PY
# The listener signing secret must match stripe-webhook.env; provision that file
# privately with the same Stripe account before starting (never print it here).
export STRIPE_API_KEY="$STRIPE_TEST_SECRET_KEY"
docker rm -f "$forwarder" >/dev/null 2>&1 || true
docker run -d --log-driver=none --name "$forwarder" --network host -e STRIPE_API_KEY \
  stripe/stripe-cli:v1.55.3 listen --forward-to http://localhost:8069/payment/stripe/webhook \
  --events payment_intent.processing,payment_intent.amount_capturable_updated,payment_intent.succeeded,payment_intent.payment_failed,payment_intent.canceled,setup_intent.succeeded,charge.refunded,charge.refund.updated \
  --log-level error >/dev/null
# Do not expose CLI output: its startup banner can include the signing secret.
echo 'Q Club Stripe test provider configured; local webhook forwarding started.'
