"""Збір даних кабінету через Meta Marketing API (токен лише ads_read).

Токен береться зі змінної середовища (за замовчуванням META_TOKEN), у файли не пишеться.
Результат: CSV у папці data/ з тими ж заголовками, що в експорті Ads Manager,
тож решта процесу однакова для API-режиму й режиму ручного експорту.

Запуск:  python fetch_meta.py --config config.json
Перевірка без мережі: python fetch_meta.py --config config.json --self-test
"""
import argparse, csv, json, os, sys, time, urllib.parse, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, with_defaults

RANK = {'above_average': 'Above average', 'average': 'Average', 'below_average': 'Below average',
        'below_average_10': 'Below average', 'below_average_20': 'Below average', 'below_average_35': 'Below average',
        'UNKNOWN': '-'}
PLATFORM = {'facebook': 'Facebook', 'instagram': 'Instagram', 'audience_network': 'Audience Network',
            'messenger': 'Messenger', 'threads': 'Threads'}


class Api:
    def __init__(self, version, token, fetcher=None):
        self.base = f'https://graph.facebook.com/{version}'
        self.token = token
        self.fetcher = fetcher  # для тесту без мережі

    def _open(self, url):
        if self.fetcher:
            return self.fetcher(url)
        req = urllib.request.Request(url, headers={'User-Agent': 'audit-kit/1.0'})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode('utf-8'))

    def get(self, path, params):
        q = dict(params)
        q['access_token'] = self.token
        url = f'{self.base}/{path}?' + urllib.parse.urlencode(q)
        out = []
        while url:
            for attempt in range(4):
                try:
                    data = self._open(url)
                    break
                except urllib.error.HTTPError as e:
                    body = e.read().decode('utf-8', errors='replace')
                    try:
                        err = json.loads(body).get('error', {})
                    except Exception:
                        err = {}
                    if err.get('code') in (4, 17, 32, 613) and attempt < 3:  # ліміти запитів
                        time.sleep(30 * (attempt + 1)); continue
                    raise SystemExit(f'Помилка API {e.code}: {err.get("message", body[:200])}')
            else:
                raise SystemExit('Забагато невдалих спроб')
            out.extend(data.get('data', []))
            url = data.get('paging', {}).get('next')
        return out


def action(lst, atype):
    for a in lst or []:
        if a.get('action_type') == atype:
            return float(a.get('value', 0))
    return 0.0


def metrics_row(r, cfg):
    pa = cfg['purchase_action']
    spend = float(r.get('spend', 0) or 0)
    imps = float(r.get('impressions', 0) or 0)
    clicks = float(r.get('inline_link_clicks', 0) or 0)
    pur = action(r.get('actions'), pa) or action(r.get('actions'), 'omni_purchase')
    val = action(r.get('action_values'), pa) or action(r.get('action_values'), 'omni_purchase')
    return {
        'Amount spent (USD)': round(spend, 2), 'Purchases conversion value': round(val, 2), 'Purchases': pur,
        'Impressions': imps, 'Reach': r.get('reach', 0), 'Frequency': r.get('frequency', 0),
        'CPM (cost per 1,000 impressions) (USD)': r.get('cpm', 0), 'Link clicks': clicks,
        'CTR (link click-through rate)': r.get('inline_link_click_ctr', 0),
        'Landing page views': action(r.get('actions'), 'landing_page_view'),
        'Adds to cart': action(r.get('actions'), 'add_to_cart'),
        'Checkouts initiated': action(r.get('actions'), 'initiate_checkout'),
    }


def write_csv(path, rows):
    if not rows:
        print('  (порожньо)', os.path.basename(path)); return
    cols = []
    for r in rows:
        for k in r:
            if k not in cols: cols.append(k)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f'  {os.path.basename(path)}: {len(rows)} рядків')


def run(cfg, api):
    act = cfg['ad_account_id']
    tr = json.dumps({'since': cfg['period_start'], 'until': cfg['period_end']})
    common = {'time_range': tr, 'limit': 500}
    base_fields = 'spend,impressions,reach,frequency,cpm,inline_link_clicks,inline_link_click_ctr,actions,action_values'
    period = {'Reporting starts': cfg['period_start'], 'Reporting ends': cfg['period_end']}
    data = cfg['_data']

    # 1. кампанії, групи, оголошення: усі об'єкти (щоб порахувати кампанії без витрат) + insights
    for level, edge, idf, namef, delf, namecol, delcol in (
            ('campaign', 'campaigns', 'campaign_id', 'campaign_name', 'effective_status', 'Campaign name', 'Campaign delivery'),
            ('adset', 'adsets', 'adset_id', 'adset_name', 'effective_status', 'Ad set name', 'Ad set delivery'),
            ('ad', 'ads', 'ad_id', 'ad_name', 'effective_status', 'Ad name', 'Ad delivery')):
        objs = {o['id']: o for o in api.get(f'{act}/{edge}', {'fields': 'name,effective_status', 'limit': 500})}
        fields = f'{idf},{base_fields}'
        if level == 'ad':
            fields += ',quality_ranking,engagement_rate_ranking,conversion_rate_ranking'
        ins = {r[idf]: r for r in api.get(f'{act}/insights', dict(common, level=level, fields=fields))}
        rows = []
        for oid, o in objs.items():
            r = ins.get(oid, {})
            row = dict(period); row[namecol] = o.get('name', ''); row[delcol] = o.get('effective_status', '').lower()
            row.update(metrics_row(r, cfg))
            if level == 'ad':
                row['Quality ranking'] = RANK.get(r.get('quality_ranking', 'UNKNOWN'), '-')
                row['Engagement rate ranking'] = RANK.get(r.get('engagement_rate_ranking', 'UNKNOWN'), '-')
                row['Conversion rate ranking'] = RANK.get(r.get('conversion_rate_ranking', 'UNKNOWN'), '-')
            rows.append(row)
        write_csv(os.path.join(data, {'campaign': 'campaigns', 'adset': 'adsets', 'ad': 'ads'}[level] + '.csv'), rows)

    # 2. плейсменти
    rows = []
    for r in api.get(f'{act}/insights', dict(common, level='campaign', fields=f'campaign_name,{base_fields}', breakdowns='publisher_platform,platform_position')):
        row = dict(period); row['Campaign name'] = r.get('campaign_name', '')
        row['Platform'] = PLATFORM.get(r.get('publisher_platform'), r.get('publisher_platform', ''))
        pos = (r.get('platform_position') or '').replace('_', ' ').title()
        row['Placement'] = pos
        row.update(metrics_row(r, cfg)); rows.append(row)
    write_csv(os.path.join(data, 'placement.csv'), rows)

    # 3. вік і стать
    rows = []
    for r in api.get(f'{act}/insights', dict(common, level='campaign', fields=f'campaign_name,{base_fields}', breakdowns='age,gender')):
        row = dict(period); row['Campaign name'] = r.get('campaign_name', ''); row['Age'] = r.get('age', ''); row['Gender'] = r.get('gender', '')
        row.update(metrics_row(r, cfg)); rows.append(row)
    write_csv(os.path.join(data, 'agegender.csv'), rows)

    # 4. по днях (рівень акаунта)
    rows = []
    for r in api.get(f'{act}/insights', dict(common, level='account', fields=base_fields, time_increment=1)):
        row = {'Day': r.get('date_start', '')}; row.update(metrics_row(r, cfg)); rows.append(row)
    write_csv(os.path.join(data, 'daily.csv'), rows)


def self_test():
    """Мок API: перевіряє, що код збирає CSV у потрібному форматі, без токена й мережі."""
    import tempfile
    tmp = tempfile.mkdtemp()
    cfg = with_defaults({'ad_account_id': 'act_1', 'period_start': '2026-01-01', 'period_end': '2026-01-31', '_data': tmp})
    ins = {'spend': '100.5', 'impressions': '10000', 'reach': '8000', 'frequency': '1.25', 'cpm': '10.05',
           'inline_link_clicks': '150', 'inline_link_click_ctr': '1.5',
           'actions': [{'action_type': 'purchase', 'value': '5'}, {'action_type': 'add_to_cart', 'value': '20'}],
           'action_values': [{'action_type': 'purchase', 'value': '250'}]}

    def fake(url):
        p = urllib.parse.urlparse(url); q = urllib.parse.parse_qs(p.query)
        if p.path.endswith('/insights'):
            row = dict(ins, campaign_id='c1', adset_id='s1', ad_id='a1', campaign_name='Camp', date_start='2026-01-02',
                       quality_ranking='above_average', engagement_rate_ranking='average', conversion_rate_ranking='below_average',
                       publisher_platform='instagram', platform_position='instagram_reels', age='25-34', gender='female')
            return {'data': [row]}
        return {'data': [{'id': 'c1', 'name': 'Camp', 'effective_status': 'ACTIVE'}, {'id': 's1', 'name': 'Set', 'effective_status': 'PAUSED'},
                         {'id': 'a1', 'name': 'Ad', 'effective_status': 'ACTIVE'}, {'id': 'zz', 'name': 'Empty', 'effective_status': 'PAUSED'}]}
    run(cfg, Api('v0', 'TEST', fake))
    camp = open(os.path.join(tmp, 'campaigns.csv'), encoding='utf-8').read().splitlines()
    assert len(camp) == 5, camp  # заголовок + 4 об'єкти (одна без витрат)
    assert 'Amount spent (USD)' in camp[0] and '100.5' in camp[1], camp
    print('self-test OK:', tmp)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        self_test(); sys.exit(0)
    cfg = with_defaults(load_config(a.config))
    tok = os.environ.get(cfg['token_env'])
    if not tok:
        sys.exit(f'Задайте токен у змінній середовища {cfg["token_env"]} (токен ads_read із модуля 1). У файли й чат його не вставляйте.')
    for k in ('ad_account_id', 'period_start', 'period_end'):
        if k not in cfg: sys.exit(f'У config.json немає "{k}"')
    run(cfg, Api(cfg['api_version'], tok))
    print('Готово. Далі: python run_audit.py --config config.json --skip-fetch')
