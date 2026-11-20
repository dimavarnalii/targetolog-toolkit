"""Аналіз даних кабінету за правилами -> work/report.json.

Кожна знахідка спирається на цифри з файлів. Мала вибірка (менше за min_spend_for_conclusion)
не дає висновку, а лише позначається. Висновки це гіпотези: фінальне слово за спеціалістом.

Запуск: python analyze.py --config config.json
"""
import re, argparse, collections, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, with_defaults, read_csv, num

SP, VAL, PUR = 'Amount spent (USD)', 'Purchases conversion value', 'Purchases'
SEV = {'КРИТИЧНО': 0, 'УВАГА': 1, 'ІНСАЙТ': 2, 'МОЖЛИВІСТЬ': 3}
RANKS = {'Above average': 'вище', 'Average': 'середня', 'Below average': 'нижче'}


def agg(rows, keyf):
    d = collections.defaultdict(lambda: {'sp': 0.0, 'val': 0.0, 'pur': 0.0, 'imp': 0.0, 'clk': 0.0})
    for r in rows:
        a = d[keyf(r)]
        a['sp'] += num(r.get(SP)); a['val'] += num(r.get(VAL)); a['pur'] += num(r.get(PUR))
        a['imp'] += num(r.get('Impressions')); a['clk'] += num(r.get('Link clicks'))
    return d


roas_of = lambda a: a['val'] / a['sp'] if a['sp'] else 0.0
cpa_of = lambda a: a['sp'] / a['pur'] if a['pur'] else None
ctr_of = lambda a: a['clk'] / a['imp'] * 100 if a['imp'] else 0.0


def analyze(cfg):
    D = cfg['_data']; MIN = cfg['min_spend_for_conclusion']
    camp = read_csv(os.path.join(D, 'campaigns.csv'))
    if not camp:
        sys.exit(f'Немає {D}\\campaigns.csv. Покладіть експорт кампаній (Ads Manager) або запустіть fetch_meta.py.')
    # валюта береться із заголовка стовпця витрат: «Amount spent (UAH)» і т. д.
    global SP
    for h in camp[0]:
        m = re.fullmatch(r'Amount spent \((\w{3})\)', h.strip())
        if m:
            SP = h; cfg['currency'] = m.group(1); break
    else:
        sys.exit('У файлі кампаній немає стовпця «Amount spent (XXX)». Додайте його в колонки експорту.')
    adsets = read_csv(os.path.join(D, 'adsets.csv')); ads = read_csv(os.path.join(D, 'ads.csv'))
    pl_rows = read_csv(os.path.join(D, 'placement.csv')); ag_rows = read_csv(os.path.join(D, 'agegender.csv'))
    daily = read_csv(os.path.join(D, 'daily.csv'))
    site = json.load(open(os.path.join(D, 'site.json'), encoding='utf-8')) if os.path.exists(os.path.join(D, 'site.json')) else None
    anon = cfg['anonymize']

    act = sorted([r for r in camp if num(r.get(SP)) > 0], key=lambda r: -num(r.get(SP)))
    if not act:
        sys.exit('У файлі кампаній немає жодної з витратами за період.')
    spend = sum(num(r[SP]) for r in act); val = sum(num(r[VAL]) for r in act); pur = sum(num(r[PUR]) for r in act)
    imp = sum(num(r.get('Impressions')) for r in act); clk = sum(num(r.get('Link clicks')) for r in act)
    roas = val / spend; n_all = len(camp); zero = n_all - len(act)
    period = f"{camp[0].get('Reporting starts', cfg.get('period_start', ''))} — {camp[0].get('Reporting ends', cfg.get('period_end', ''))}"
    cur = cfg['currency']

    label = {}
    def nm(kind, i, raw):
        return {'c': f'К{i}', 'a': f'Оголошення {i}', 's': f'Група {i}'}[kind] if anon else raw
    cname = {r['Campaign name']: nm('c', i, r['Campaign name']) for i, r in enumerate(act, 1)}

    findings = []
    def F(tag, title, text, extra=None, action=None, effect=None, urgency=None):
        findings.append({'tag': tag, 'title': title, 'text': text, 'extra': extra, 'action': action, 'effect': effect, 'urgency': urgency})

    # ---- таблиця кампаній
    camp_t = []
    for r in act:
        a = {'sp': num(r[SP]), 'val': num(r[VAL]), 'pur': num(r[PUR])}
        camp_t.append({'name': cname[r['Campaign name']], 'state': 'активна' if r.get('Campaign delivery', '').lower() in ('active', 'ACTIVE'.lower()) else 'вимкнена',
                       'spend': a['sp'], 'pur': a['pur'], 'cpa': cpa_of(a), 'roas': roas_of(a), 'freq': num(r.get('Frequency')), 'ctr': num(r.get('CTR (link click-through rate)'))})
    top = camp_t[0]; top_share = top['spend'] / spend * 100
    top2_share = sum(c['spend'] for c in camp_t[:2]) / spend * 100

    # R1 концентрація й частота
    if top_share >= cfg['concentration_warn_pct']:
        F('УВАГА', f'Бюджет тримається на одній кампанії: {top_share:.0f}%',
          f'Кампанія {top["name"]} забрала {top_share:.0f}% витрат, дві перші разом {top2_share:.0f}%.' + (f' Її накопичена частота {top["freq"]:.1f} за період.' if top['freq'] else '') + ' Якщо вона втомиться, результат просяде одразу.',
          'Частота накопичена за весь період, тому сама по собі це не вирок.',
          'Підготувати 3–5 нових креативів і запустити окремою кампанією', 'менша залежність від однієї кампанії', '2 тижні')
    elif top['freq'] >= cfg['frequency_warn']:
        F('УВАГА', f'Висока частота головної кампанії: {top["freq"]:.1f}', f'Кампанія {top["name"]} показує рекламу одним і тим самим людям у середньому {top["freq"]:.1f} раза за період.', 'Частота накопичена за весь період.', 'Оновити креативи головної кампанії', 'менше втоми аудиторії', '2 тижні')
    # R3 захаращеність
    if zero >= 10 and zero / n_all >= cfg['zero_campaigns_warn_share']:
        F('УВАГА', f'Акаунт захаращений: {zero} із {n_all} кампаній без витрат', 'Порожні кампанії не шкодять доставці, але ускладнюють звітність і передачу акаунта іншому спеціалісту.', None,
          'Архівувати кампанії без витрат, ввести правило назв', 'чистіша звітність', '2 тижні')

    # ---- адсети: тип аудиторії
    aud = []
    if adsets:
        def atype(r):
            n = r.get('Ad set name', '').lower()
            if any(p in n for p in cfg['lookalike_name_patterns']): return 'Look-alike'
            if any(p in n for p in cfg['retargeting_name_patterns']): return 'Ретаргетинг'
            return 'Інші (холодні / широкі)'
        for k, a in sorted(agg(adsets, atype).items(), key=lambda x: -x[1]['sp']):
            if a['sp'] > 0: aud.append({'name': k, 'spend': a['sp'], 'roas': roas_of(a), 'pur': a['pur']})
        by = {x['name']: x for x in aud}
        for k in ('Look-alike', 'Ретаргетинг'):
            o = by.get('Інші (холодні / широкі)')
            if k in by and o:
                x = by[k]
                if x['spend'] < MIN:
                    F('ІНСАЙТ', f'{k}: даних замало (${x["spend"]:,.0f})', f'ROAS {x["roas"]:.2f} проти {o["roas"]:.2f} в інших, але витрати нижчі за поріг ${MIN}: висновку немає.', 'Тип аудиторії визначено за назвами груп оголошень.', f'Не масштабувати {k} до ${MIN * 4:,.0f}+ витрат', 'не палити бюджет на малій вибірці', 'постійно')
                elif x['roas'] < o['roas'] * 0.75:
                    F('ІНСАЙТ', f'{k} слабший за інші: ROAS {x["roas"]:.2f} проти {o["roas"]:.2f}', f'На {k} пішло ${x["spend"]:,.0f}.', 'Тип аудиторії визначено за назвами груп оголошень.', f'Перерозподілити бюджет із {k} на кращі групи', 'вищий ROAS', '2 тижні')
                elif x['roas'] > o['roas'] * 1.25:
                    F('МОЖЛИВІСТЬ', f'{k} сильніший за інші: ROAS {x["roas"]:.2f} проти {o["roas"]:.2f}', f'Витрати ${x["spend"]:,.0f}. Є сенс обережно збільшити частку.', 'Тип аудиторії визначено за назвами груп оголошень.')

    # ---- оголошення
    ads_t = []; vid_roas = oth_roas = None; top2ads = 0
    ads_act = sorted([r for r in ads if num(r.get(SP)) >= 5], key=lambda r: -num(r[SP]))
    if ads_act:
        for i, r in enumerate(ads_act, 1):
            s_, v_, p_ = num(r[SP]), num(r[VAL]), num(r[PUR])
            rk = lambda k: RANKS.get((r.get(k) or '').split(' - ')[0].strip(), '—')
            ads_t.append({'name': nm('a', i, r.get('Ad name', '')), 'state': 'активне' if (r.get('Ad delivery') or '').lower() == 'active' else 'вимкнене', 'spend': s_, 'pur': p_, 'roas': v_ / s_, 'freq': num(r.get('Frequency')),
                          'quality': rk('Quality ranking'), 'conv': rk('Conversion rate ranking')})
        top2ads = sum(a['spend'] for a in ads_t[:2]) / spend * 100
        pats = cfg['video_name_patterns']
        isv = lambda r: any((r.get('Ad name') or '').lower().startswith(p) for p in pats)
        v_rows = [r for r in ads_act if isv(r)]; o_rows = [r for r in ads_act if not isv(r)]
        if v_rows and o_rows:
            vs, os_ = sum(num(r[SP]) for r in v_rows), sum(num(r[SP]) for r in o_rows)
            vid_roas, oth_roas = sum(num(r[VAL]) for r in v_rows) / vs, sum(num(r[VAL]) for r in o_rows) / os_
            if min(vs, os_) >= MIN and max(vid_roas, oth_roas) > 0 and abs(vid_roas - oth_roas) / max(vid_roas, oth_roas) >= 0.15:
                better = 'Відео' if vid_roas > oth_roas else 'Інші формати'
                F('ІНСАЙТ', f'{better} працюють краще: ROAS {max(vid_roas, oth_roas):.2f} проти {min(vid_roas, oth_roas):.2f}', 'Формат визначено за початком назви оголошення (налаштовується в config.json), це припущення.', None,
                  f'Збільшити частку формату «{better.lower()}» у нових креативах', 'вищий ROAS нових оголошень', '2 тижні')
        if top2ads >= 50:
            F('УВАГА', f'Два оголошення забирають {top2ads:.0f}% бюджету', f'Нових креативів у ротації замало: частота першого {ads_t[0]["freq"]:.1f}.', None, 'Додати нові оголошення в ротацію', 'менша залежність від двох оголошень', '2 тижні')
        weak = [a for a in ads_t if a['spend'] >= MIN and (a['quality'] == 'нижче' or a['conv'] == 'нижче')]
        if weak:
            F('УВАГА', f'{len(weak)} оголошень із рейтингом Meta «нижче середнього»', 'Meta оцінює якість або конверсію гірше, ніж у конкурентів на тих самих показах: ' + ', '.join(a['name'] for a in weak[:4]) + '.', None, 'Замінити або переробити оголошення з низьким рейтингом', 'вищий ROAS', '2 тижні')

    # ---- плейсменти
    def plkey(r):
        pf = r.get('Platform', ''); pn = r.get('Placement', '')
        pn = pn.replace(pf, '').strip() or pn
        if pf == 'Threads': return 'Threads'
        short = {'Facebook': 'FB', 'Instagram': 'IG'}.get(pf, pf)
        return f'{short} {pn}'.strip()
    pl_t = []
    if pl_rows:
        for k, a in sorted(agg(pl_rows, plkey).items(), key=lambda x: -x[1]['sp']):
            if a['sp'] >= 5: pl_t.append({'name': k, 'spend': a['sp'], 'share': a['sp'] / spend * 100, 'pur': a['pur'], 'cpa': cpa_of(a), 'roas': roas_of(a), 'ctr': ctr_of(a)})
        best = [p for p in pl_t if p['spend'] >= MIN and p['cpa']]
        for p in pl_t:
            if p['spend'] >= max(MIN, spend * 0.05) and p['roas'] < roas * cfg['placement_bad_roas_ratio']:
                ref = min((q['cpa'] for q in best if q is not p and q['cpa']), default=None)
                F('КРИТИЧНО', f'{p["name"]}: ROAS {p["roas"]:.2f}' + (f' і ціна покупки ${p["cpa"]:.2f}' if p['cpa'] else ''),
                  f'Плейсмент отримав ${p["spend"]:,.0f} ({p["share"]:.0f}% бюджету) при ROAS значно нижчому за середній {roas:.2f}.' + (f' У найкращих плейсментах ціна покупки від ${ref:.2f}.' if ref else ''),
                  'Розріз за плейсментами. Вибірка достатня для рішення «зменшити», не для «вимкнути назавжди».', f'Зменшити бюджет {p["name"]}, перенести на кращі плейсменти', 'нижча ціна покупки', 'цього тижня')
            elif p['spend'] < max(MIN, spend * 0.05) and p['spend'] >= 10 and p['roas'] >= roas * 1.5 and p['pur'] >= 3:
                F('МОЖЛИВІСТЬ', f'{p["name"]}: ROAS {p["roas"]:.2f} на малому бюджеті', f'Витрати лише ${p["spend"]:,.0f}, тож це напрям для тесту, а не висновок.')

    # ---- вік і стать
    ag_t = []; fem = None
    if ag_rows:
        for k, a in sorted(agg(ag_rows, lambda r: r.get('Age', '')).items()):
            if a['sp'] >= 5 and k not in ('Unknown', ''): ag_t.append({'name': k, 'spend': a['sp'], 'share': a['sp'] / spend * 100, 'pur': a['pur'], 'cpa': cpa_of(a), 'roas': roas_of(a)})
        gd = agg(ag_rows, lambda r: (r.get('Gender') or '').lower())
        tot_g = sum(a['sp'] for a in gd.values())
        if tot_g and 'female' in gd: fem = gd['female']['sp'] / tot_g * 100
        for g_ in ag_t:
            if g_['share'] >= 15 and g_['spend'] >= MIN and g_['roas'] < roas * cfg['age_bad_roas_ratio']:
                others = [x['roas'] for x in ag_t if x is not g_ and x['spend'] >= MIN]
                F('ІНСАЙТ', f'Вік {g_["name"]}: ROAS {g_["roas"]:.2f} при {g_["share"]:.0f}% витрат', 'Інші групи: ' + ', '.join(f'{x["name"]} {x["roas"]:.2f}' for x in ag_t if x is not g_ and x['spend'] >= MIN) + '.',
                  None, f'Зменшити частку бюджету на вік {g_["name"]} або дати йому окремий креатив', 'вищий ROAS', '2 тижні')
        if fem and (fem >= 90 or fem <= 10):
            F('ІНСАЙТ', f'Аудиторія майже одностатева: {"жінки" if fem >= 50 else "чоловіки"} {max(fem, 100 - fem):.0f}% витрат', 'Таргетинг уже сфокусований за статтю, головний важіль це вік і креатив.')

    # ---- тренд по днях
    trend = None
    if daily:
        rows = sorted([r for r in daily if r.get('Day')], key=lambda r: r['Day'])
        if len(rows) >= 28:
            w1, w0 = rows[-14:], rows[-28:-14]
            def w(rs):
                s = sum(num(r[SP]) for r in rs); v = sum(num(r[VAL]) for r in rs); p = sum(num(r[PUR]) for r in rs)
                return {'sp': s, 'val': v, 'pur': p}
            a1, a0 = w(w1), w(w0)
            if a0['sp'] >= MIN and a1['sp'] >= MIN:
                r1, r0 = roas_of(a1), roas_of(a0); ch = (r1 / r0 - 1) * 100 if r0 else 0
                trend = {'roas_prev': r0, 'roas_last': r1, 'change_pct': ch, 'spend_prev': a0['sp'], 'spend_last': a1['sp']}
                if ch <= -cfg['trend_warn_pct']:
                    F('УВАГА', f'ROAS просів на {abs(ch):.0f}% за останні 14 днів', f'{r0:.2f} → {r1:.2f} (витрати ${a0["sp"]:,.0f} → ${a1["sp"]:,.0f}). Перевірте втому креативів і зміни в сайті чи ціні.', None, 'З\'ясувати причину просідання ROAS за останні 2 тижні', 'повернення ROAS', 'цього тижня')
                elif ch >= cfg['trend_warn_pct']:
                    F('МОЖЛИВІСТЬ', f'ROAS зріс на {ch:.0f}% за останні 14 днів', f'{r0:.2f} → {r1:.2f}. Є сенс перевірити, що саме спрацювало, і закріпити.')

    # ---- воронка
    funnel = None
    src = daily if daily and num(daily[0].get('Adds to cart')) + sum(num(r.get('Adds to cart')) for r in daily) > 0 else camp
    stages = [('Покази', 'Impressions'), ('Кліки за посиланням', 'Link clicks'), ('Перегляди сторінки', 'Landing page views'), ('Додали в кошик', 'Adds to cart'), ('Оформлення', 'Checkouts initiated'), ('Покупки', 'Purchases')]
    tot = {k: sum(num(r.get(col)) for r in src) for k, col in stages}
    present = [(k, tot[k]) for k, _ in stages if tot[k] > 0]
    if len(present) >= 4 and tot.get('Додали в кошик', 0) > 0:
        funnel = []; worst = None
        for i, (k, v) in enumerate(present):
            conv = v / present[i - 1][1] * 100 if i else None
            funnel.append({'stage': k, 'value': v, 'conv': conv})
            if i and k != 'Кліки за посиланням' and present[i - 1][0] != 'Покази':
                if worst is None or conv < worst[1]: worst = (k, conv, present[i - 1][0])
        if worst:
            F('ІНСАЙТ', f'Найслабший перехід воронки: {worst[2]} → {worst[0]} ({worst[1]:.1f}%)', 'Це найнижча конверсія між сусідніми етапами в цих даних. Порівнюйте з минулими періодами й власними нормами ніші: універсальних еталонів немає.')

    # ---- сайт
    site_rows = []; site_src = None
    if site:
        ps = site.get('psi') or {}; ht = site.get('html') or {}
        site_src = ps.get('source') if ps else None
        if ps and 'error' not in ps:
            def rate(v, good, ok): return 'добре' if v <= good else 'межа' if v <= ok else 'повільно'
            if ps.get('fcp_s') is not None: site_rows.append(['Перший вміст (FCP)', f'{ps["fcp_s"]} с', rate(ps['fcp_s'], 1.8, 3.0)])
            if ps.get('lcp_s') is not None: site_rows.append(['Найбільший елемент (LCP)', f'{ps["lcp_s"]} с', rate(ps['lcp_s'], 2.5, 4.0)])
            if ps.get('load_s') is not None: site_rows.append(['Повне завантаження', f'{ps["load_s"]} с', rate(ps['load_s'], 3, 5)])
            if ps.get('tbt_ms') is not None: site_rows.append(['Блокування (TBT)', f'{ps["tbt_ms"]} мс', 'добре' if ps['tbt_ms'] <= 200 else 'межа' if ps['tbt_ms'] <= 600 else 'повільно'])
            if ps.get('cls') is not None: site_rows.append(['Зсув макета (CLS)', str(ps['cls']), 'добре' if ps['cls'] <= .1 else 'межа' if ps['cls'] <= .25 else 'слабко'])
            if ps.get('total_kb'):
                mb = ps['total_kb'] / 1024
                site_rows.append(['Вага сторінки', f'{mb:.1f} МБ' + (f', {ps["requests"]} запитів' if ps.get('requests') else ''), 'критично важка' if mb > 3 else 'межа' if mb > 1.6 else 'добре'])
                if mb > 3:
                    F('КРИТИЧНО', f'Сторінка важить {mb:.1f} МБ', 'Важка сторінка повільно відкривається на мобільному інтернеті: частина людей, за яких заплачено в рекламі, не дочікується.' + (f' Повне завантаження {ps["load_s"]} с.' if ps.get('load_s') else ''),
                      'Замір одного завантаження: ' + ('PageSpeed Insights.' if ps.get('source') == 'pagespeed' else 'у браузері спеціаліста, десктоп.'), 'Стиснути зображення та скрипти сторінки до 1–2 МБ', 'швидший перший екран, менше втрат трафіку', 'цього тижня')
            elif ps.get('lcp_s') and ps['lcp_s'] > 4:
                F('УВАГА', f'Повільне завантаження: LCP {ps["lcp_s"]} с', 'Перший великий елемент з\'являється пізніше за 4 с.', None, 'Оптимізувати перший екран і зображення', 'менше втрат трафіку', 'цього тижня')
            if ps.get('score') is not None: site_rows.insert(0, ['Оцінка швидкості (мобільна)', f'{ps["score"]}/100', 'добре' if ps['score'] >= 90 else 'межа' if ps['score'] >= 50 else 'слабко'])
        if ht:
            if ht.get('h1_count') is not None: site_rows.append(['Заголовок H1', 'є' if ht['h1_count'] else 'відсутній', 'ок' if ht['h1_count'] else 'слабко для SEO'])
            if ht.get('images_total'):
                share = ht['images_no_alt'] / ht['images_total']
                site_rows.append(['Опис зображень (alt)', f'{ht["images_no_alt"]} із {ht["images_total"]} без опису', 'ок' if share < .2 else 'слабко'])
            site_rows.append(['Мета-опис, viewport', 'є' if ht.get('meta_description') and ht.get('viewport') else 'немає', 'ок' if ht.get('meta_description') and ht.get('viewport') else 'слабко'])
            if not ht.get('h1_count') and ht.get('h1_count') is not None:
                F('УВАГА', 'На сторінці немає заголовка H1', 'Це ускладнює для пошукових систем розуміння теми сторінки.', None, 'Додати H1 і описи зображень (alt)', 'краща видимість у пошуку', '2 тижні')
        for n in site.get('notes', []):  # ручні спостереження (наприклад, перший екран)
            F(n.get('tag', 'УВАГА'), n['title'], n['text'], n.get('extra'), n.get('action'), n.get('effect'), n.get('urgency'))

    # ---- беззбитковість
    be = None; m = cfg.get('margin_percent')
    if m:
        be = {'margin': m, 'roas_be': 100 / m, 'roas': roas, 'ok': roas > 100 / m}
        if not be['ok']:
            F('КРИТИЧНО', f'ROAS {roas:.2f} нижчий за беззбитковий {100 / m:.2f}', f'При маржі {m}% до реклами акаунт працює в мінус. Перевірте маржу й LTV повторних покупок.', None, 'Підняти ROAS або знизити ціну покупки, інакше масштабувати не можна', 'вихід у плюс', 'цього тижня')
    else:
        F('ІНСАЙТ', f'Прибутковість не оцінена: немає маржі', f'ROAS {roas:.2f} можна оцінити лише з маржею. Вкажіть margin_percent у config.json.', 'Беззбитковий ROAS = 100 / маржа%.')

    findings.sort(key=lambda f: SEV[f['tag']])
    prios, seen = [], set()
    for f in findings:
        if f.get('action') and f['action'] not in seen:
            seen.add(f['action']); prios.append({'action': f['action'], 'effect': f['effect'] or '', 'urgency': f['urgency'] or '2 тижні'})
    prios.append({'action': 'Звірити цінність покупок із реальною виручкою (магазин, CRM, Google Analytics)', 'effect': 'розуміння реального ROAS', 'urgency': 'місяць'})

    limits = ['Дані: ' + ', '.join(n for n, ok in (('кампанії', True), ('групи', bool(adsets)), ('оголошення', bool(ads)), ('плейсменти', bool(pl_rows)), ('вік і стать', bool(ag_rows)), ('по днях', bool(daily))) if ok) + ' за один період.',
              'Атрибуція кабінету (вікно за замовчуванням) завищує або занижує результат порівняно з реальними продажами.',
              f'Вибірки до ${MIN} не дають висновків.', 'Висновки це правила на цифрах: фінальне рішення за спеціалістом.']
    missing = [t for t, ok in (('Розріз по днях (тренд ROAS, зростання частоти)', bool(daily)), ('Воронка (кошик, оформлення)', funnel is not None), ('Ретаргетинг проти холодної аудиторії (потрібні групи оголошень з типами в назвах)', bool(aud)), ('Звірка з Google Analytics чи CRM', False)) if not ok]

    return {'meta': {'client': cfg['client_name_anonymized'] if anon else cfg['client_name'], 'period': period, 'currency': cur, 'anonymized': anon, 'site_url': None if anon else (site or {}).get('url'), 'generated': datetime.date.today().isoformat()},
            'kpis': {'spend': spend, 'purchases': pur, 'value': val, 'roas': roas, 'cpa': spend / pur if pur else None, 'cpm': spend / imp * 1000 if imp else 0, 'ctr': clk / imp * 100 if imp else 0,
                     'top_freq': top['freq'], 'zero': zero, 'n_all': n_all, 'n_act': len(act), 'active_now': sum(1 for c in camp_t if c['state'] == 'активна')},
            'campaigns': camp_t, 'ads': ads_t, 'audience_types': aud, 'placements': pl_t, 'ages': ag_t, 'female_share': fem, 'trend': trend, 'funnel': funnel,
            'site_rows': site_rows, 'site_source': site_src, 'breakeven': be, 'findings': findings, 'priorities': prios, 'limits': limits, 'missing': missing}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); a = ap.parse_args()
    cfg = with_defaults(load_config(a.config))
    for k in ('client_name', 'client_name_anonymized'):
        cfg.setdefault(k, 'Клієнт')
    rep = analyze(cfg)
    out = os.path.join(cfg['_work'], 'report.json'); json.dump(rep, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'Знахідок: {len(rep["findings"])}; збережено {out}')
