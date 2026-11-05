-- ISO-001: run with psql -X -qAt -v ON_ERROR_STOP=1.
-- No writes, temporary tables, ids or timestamps in the fingerprint.
BEGIN READ ONLY;
SET LOCAL timezone = 'UTC';
SET LOCAL extra_float_digits = 3;
-- Missing/ambiguous AUSHARE must fail rather than produce a vacuous comparison.
SELECT 'AUSHARE count=' || (1 / CASE WHEN count(*) = 1 THEN 1 ELSE 0 END)::text COLLATE "C" AS fingerprint
FROM website WHERE name = 'AUSHARE';

SELECT 'website|' || jsonb_build_object(
    'name', w.name, 'domain', w.domain, 'company', c.name,
    'default_language', l.code,
    'languages', (SELECT jsonb_agg(lang.code ORDER BY lang.code COLLATE "C")
                  FROM website_lang_rel rel JOIN res_lang lang ON lang.id = rel.lang_id
                  WHERE rel.website_id = w.id),
    'public_user', public_user.login, 'partner', partner.name, 'theme', theme.name,
    'settings', (SELECT jsonb_object_agg(k, v) FROM jsonb_each(to_jsonb(w)) AS e(k, v)
                 WHERE k NOT IN ('id', 'create_date', 'write_date', 'create_uid', 'write_uid',
                                 'company_id', 'default_lang_id')
                   AND k NOT LIKE '%\_id' ESCAPE '\' AND k NOT LIKE '%\_ids' ESCAPE '\')
)::text COLLATE "C" AS fingerprint
FROM website w
LEFT JOIN res_company c ON c.id = w.company_id
LEFT JOIN res_lang l ON l.id = w.default_lang_id
LEFT JOIN res_users public_user ON public_user.id = w.user_id
LEFT JOIN res_partner partner ON partner.id = public_user.partner_id
LEFT JOIN ir_module_module theme ON theme.id = w.theme_id
WHERE w.name = 'AUSHARE'
ORDER BY fingerprint;

SELECT 'page|' || jsonb_build_object(
    'website', w.name, 'url', p.url, 'name', to_jsonb(v)->'name',
    'published', to_jsonb(p)->'is_published', 'website_published', to_jsonb(p)->'website_published',
    'indexed', to_jsonb(p)->'website_indexed', 'publish_date', to_jsonb(p)->'date_publish',
    'view_key', v.key, 'active', v.active, 'sequence', to_jsonb(p)->'sequence'
)::text COLLATE "C" AS fingerprint
FROM website_page p
LEFT JOIN website w ON w.id = p.website_id
LEFT JOIN ir_ui_view v ON v.id = p.view_id
WHERE w.name = 'AUSHARE' OR p.website_id IS NULL
ORDER BY fingerprint;

SELECT 'menu|' || jsonb_build_object(
    'website', w.name, 'url', m.url, 'name', to_jsonb(m)->'name',
    'parent_url', parent.url, 'parent_name', to_jsonb(parent)->'name',
    'sequence', m.sequence, 'new_window', to_jsonb(m)->'new_window',
    'mega_menu', to_jsonb(m)->'is_mega_menu', 'mega_menu_content', to_jsonb(m)->'mega_menu_content'
)::text COLLATE "C" AS fingerprint
FROM website_menu m
LEFT JOIN website w ON w.id = m.website_id
LEFT JOIN website_menu parent ON parent.id = m.parent_id
WHERE w.name = 'AUSHARE' OR m.website_id IS NULL
ORDER BY fingerprint;

SELECT 'view|' || jsonb_build_object(
    'key', v.key, 'name', to_jsonb(v)->'name', 'type', v.type, 'mode', v.mode,
    'active', v.active, 'priority', v.priority, 'website', w.name,
    'inherit_key', parent.key, 'arch_md5', md5(v.arch_db::text)
)::text COLLATE "C" AS fingerprint
FROM ir_ui_view v
LEFT JOIN website w ON w.id = v.website_id
LEFT JOIN ir_ui_view parent ON parent.id = v.inherit_id
WHERE NOT EXISTS (
    SELECT 1 FROM ir_model_data d
    WHERE d.module = 'qclub_billiard' AND d.model = 'ir.ui.view' AND d.res_id = v.id
)
ORDER BY fingerprint;

SELECT 'product_template|' || jsonb_build_object(
    'name', to_jsonb(p)->'name', 'default_code', to_jsonb(p)->'default_code',
    'list_price', p.list_price, 'sale_ok', p.sale_ok,
    'is_published', to_jsonb(p)->'is_published', 'website_published', to_jsonb(p)->'website_published',
    'website', w.name, 'active', p.active
)::text COLLATE "C" AS fingerprint
FROM product_template p LEFT JOIN website w ON w.id = p.website_id
ORDER BY fingerprint;

SELECT 'product_product|' || jsonb_build_object(
    'template_name', to_jsonb(t)->'name', 'default_code', p.default_code, 'active', p.active
)::text COLLATE "C" AS fingerprint
FROM product_product p JOIN product_template t ON t.id = p.product_tmpl_id
ORDER BY fingerprint;

SELECT 'mail_template|' || jsonb_build_object(
    'name', to_jsonb(t)->'name', 'model', m.model,
    'subject_md5', md5(t.subject::text), 'body_md5', md5(t.body_html::text), 'lang', t.lang
)::text COLLATE "C" AS fingerprint
FROM mail_template t LEFT JOIN ir_model m ON m.id = t.model_id
ORDER BY fingerprint;

-- psql generates only a SELECT when the optional table exists. JSON extraction
-- also accommodates installations without the website-specific provider field.
SELECT $query$
SELECT 'payment_provider|' || jsonb_build_object(
    'code', p.code, 'state', p.state, 'website', w.name
)::text COLLATE "C" AS fingerprint
FROM payment_provider p
LEFT JOIN website w ON w.id = (to_jsonb(p)->>'website_id')::integer
ORDER BY fingerprint
$query$
WHERE to_regclass('payment_provider') IS NOT NULL
\gexec
COMMIT;
