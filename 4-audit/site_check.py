"""Перевірка посадкової сторінки -> data/site.json.

1) HTML: title, meta description, H1, зображення без alt, viewport (без браузера, лише стандартна бібліотека).
2) PageSpeed Insights API (швидкість, вага, запити). Потрібен безкоштовний ключ Google
   (PSI_API_KEY або --key): без ключа квота часто вичерпана (помилка 429).
Якщо PageSpeed недоступний, заміри можна внести вручну в site.json (поле "psi", source: "browser")
або попросити агента зняти їх у браузері.

Запуск: python site_check.py --config config.json   (адреса береться з site_url)
"""
import argparse, json, os, sys, urllib.parse, urllib.request, urllib.error
from html.parser import HTMLParser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, with_defaults

UA = 'Mozilla/5.0 (compatible; audit-kit/1.0)'


class P(HTMLParser):
    def __init__(self):
        super().__init__(); self.title = ''; self._t = False; self.meta = None; self.h1 = 0; self.imgs = 0; self.noalt = 0; self.viewport = False
    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == 'title': self._t = True
        elif tag == 'meta':
            if (a.get('name') or '').lower() == 'description': self.meta = a.get('content')
            if (a.get('name') or '').lower() == 'viewport': self.viewport = True
        elif tag == 'h1': self.h1 += 1
        elif tag == 'img':
            self.imgs += 1
            if not (a.get('alt') or '').strip(): self.noalt += 1
    def handle_endtag(self, tag):
        if tag == 'title': self._t = False
    def handle_data(self, d):
        if self._t: self.title += d


def html_check(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode('utf-8', errors='replace')
    p = P(); p.feed(body)
    return {'title': p.title.strip(), 'meta_description': p.meta, 'h1_count': p.h1, 'images_total': p.imgs,
            'images_no_alt': p.noalt, 'viewport': p.viewport, 'html_kb': round(len(body.encode('utf-8')) / 1024)}


def psi(url, key, strategy='mobile'):
    q = [('url', url), ('strategy', strategy), ('category', 'performance')]
    if key: q.append(('key', key))
    u = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?' + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=120) as r:
            d = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': f'PageSpeed API {e.code}: ' + ('квота вичерпана, створіть безкоштовний ключ' if e.code == 429 else 'помилка')}
    lh = d.get('lighthouseResult', {}); au = lh.get('audits', {})
    g = lambda k: au.get(k, {}).get('numericValue')
    reqs = au.get('network-requests', {}).get('details', {}).get('items', [])
    return {'source': 'pagespeed', 'strategy': strategy,
            'score': round(lh.get('categories', {}).get('performance', {}).get('score', 0) * 100),
            'fcp_s': round(g('first-contentful-paint') / 1000, 1) if g('first-contentful-paint') else None,
            'lcp_s': round(g('largest-contentful-paint') / 1000, 1) if g('largest-contentful-paint') else None,
            'tbt_ms': round(g('total-blocking-time')) if g('total-blocking-time') is not None else None,
            'cls': round(g('cumulative-layout-shift'), 3) if g('cumulative-layout-shift') is not None else None,
            'total_kb': round(g('total-byte-weight') / 1024) if g('total-byte-weight') else None,
            'requests': len(reqs) or None}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); ap.add_argument('--key'); ap.add_argument('--no-psi', action='store_true')
    a = ap.parse_args(); cfg = with_defaults(load_config(a.config))
    url = cfg.get('site_url')
    if not url: sys.exit('У config.json немає site_url')
    path = os.path.join(cfg['_data'], 'site.json')
    old = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
    out = dict(old); out['url'] = url
    try:
        out['html'] = html_check(url)
    except Exception as e:
        out['html'] = None; print('HTML не вдалося завантажити:', e)
    if not a.no_psi:
        res = psi(url, a.key or os.environ.get('PSI_API_KEY'))
        if 'error' in res:
            print(res['error'])
            if not old.get('psi'): out['psi'] = None  # збережемо ручні заміри, якщо вони вже є
        else:
            out['psi'] = res
    json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('Збережено', path)
