"""Спільні функції audit-kit: читання CSV і чисел."""
import csv, io, json, os


def read_text(path):
    """CSV з Ads Manager буває у cp1251, з fetch_meta.py в utf-8. Пробуємо обидва."""
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp1251'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def read_csv(path):
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(io.StringIO(read_text(path))))


def num(x):
    """Число з клітинки CSV. Порожнє, '—' або текст дають 0."""
    if x is None:
        return 0.0
    s = str(x).strip().replace(' ', '').replace(' ', '')
    if s in ('', '-', '—'):
        return 0.0
    s = s.replace('%', '')
    if s.count(',') == 1 and s.count('.') == 0:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def load_config(path):
    cfg = json.load(open(path, encoding='utf-8'))
    base = os.path.dirname(os.path.abspath(path))
    cfg['_base'] = base
    cfg['_data'] = os.path.join(base, cfg.get('data_dir', 'data'))
    cfg['_work'] = os.path.join(base, cfg.get('work_dir', 'work'))
    os.makedirs(cfg['_data'], exist_ok=True)
    os.makedirs(cfg['_work'], exist_ok=True)
    return cfg


DEFAULTS = {
    'currency': 'USD',
    'anonymize': False,
    'min_spend_for_conclusion': 50,
    'concentration_warn_pct': 30,
    'frequency_warn': 6,
    'zero_campaigns_warn_share': 0.5,
    'placement_bad_roas_ratio': 0.6,
    'age_bad_roas_ratio': 0.75,
    'trend_warn_pct': 20,
    'video_name_patterns': ['vid', 'video', 'reels', 'відео'],
    'lookalike_name_patterns': ['lal', 'lookalike'],
    'retargeting_name_patterns': ['retarget', 'remarket', 'ретаргет', 'rt_'],
    'purchase_action': 'purchase',
    'api_version': 'v23.0',
    'token_env': 'META_TOKEN',
}


def with_defaults(cfg):
    out = dict(DEFAULTS)
    out.update(cfg)
    return out
