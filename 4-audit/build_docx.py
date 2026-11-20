"""Збірка Word-аудиту з work/report.json.   python build_docx.py --config config.json"""
import argparse, json, os, sys
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, with_defaults

NAVY, AMBER, INK, MUT, LINE, SOFT = '0F172A', 'F59E0B', '111827', '6B7280', 'E5E7EB', 'F8FAFC'
TAGS = {'КРИТИЧНО': ('B91C1C', 'FEE2E2'), 'УВАГА': ('B45309', 'FEF3C7'), 'ІНСАЙТ': ('1D4ED8', 'DBEAFE'), 'МОЖЛИВІСТЬ': ('047857', 'D1FAE5')}
rgb = RGBColor.from_string


def build(cfg):
    rep = json.load(open(os.path.join(cfg['_work'], 'report.json'), encoding='utf-8'))
    M, K = rep['meta'], rep['kpis']; cur = M['currency']; sym = '$' if cur == 'USD' else cur + ' '
    ch = os.path.join(cfg['_work'], 'charts'); os.makedirs(ch, exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.edgecolor': '#d1d5db', 'axes.labelcolor': '#374151', 'xtick.color': '#6b7280', 'ytick.color': '#374151'})
    gc = lambda v: '#10b981' if v >= 1.8 else '#f59e0b' if v >= 1.0 else '#ef4444'
    roas = K['roas']

    def hbar(labs, vals, fname, xlabel, colors=None, fmt='{:.2f}', ref=None):
        labs, vals = labs[::-1], vals[::-1]
        fig, ax = plt.subplots(figsize=(7.4, max(2.2, .38 * len(labs) + .8)))
        ax.barh(labs, vals, color=[(colors(v) if colors else '#' + AMBER) for v in vals], height=.62)
        for i, v in enumerate(vals): ax.text(v + max(vals) * .015, i, fmt.format(v), va='center', fontsize=8, color='#374151')
        if ref: ax.axvline(ref, color='#0f172a', ls='--', lw=1)
        ax.set_xlim(0, max(vals) * 1.25); ax.spines[['top', 'right', 'left']].set_visible(False); ax.tick_params(length=0); ax.set_xlabel(xlabel)
        plt.tight_layout(); p = os.path.join(ch, fname); plt.savefig(p, dpi=220); plt.close(); return p

    d = Document(); s0 = d.sections[0]; s0.page_width, s0.page_height = Cm(21), Cm(29.7)
    s0.left_margin = s0.right_margin = Cm(1.9); s0.top_margin = Cm(1.6); s0.bottom_margin = Cm(1.8)
    st = d.styles['Normal']; st.font.name = 'Calibri'; st.font.size = Pt(10.5); st.font.color.rgb = rgb('1F2937')
    st.element.rPr.rFonts.set(qn('w:eastAsia'), 'Calibri'); st.paragraph_format.space_after = Pt(5); st.paragraph_format.line_spacing = 1.12

    def shade(c, fill):
        tcPr = c._tc.get_or_add_tcPr()
        for e in tcPr.findall(qn('w:shd')): tcPr.remove(e)
        sh = OxmlElement('w:shd'); sh.set(qn('w:val'), 'clear'); sh.set(qn('w:color'), 'auto'); sh.set(qn('w:fill'), fill); tcPr.append(sh)
    def borders(c, **kw):
        tcPr = c._tc.get_or_add_tcPr(); b = tcPr.find(qn('w:tcBorders'))
        if b is None: b = OxmlElement('w:tcBorders'); tcPr.append(b)
        for edge in ('top', 'left', 'bottom', 'right'):
            v = kw.get(edge); e = OxmlElement(f'w:{edge}')
            if v: e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), str(v[0])); e.set(qn('w:color'), v[1])
            else: e.set(qn('w:val'), 'nil')
            b.append(e)
    def margins(c, t=80, b=80, l=140, r=140):
        tcPr = c._tc.get_or_add_tcPr(); m = OxmlElement('w:tcMar')
        for k, v in (('top', t), ('left', l), ('bottom', b), ('right', r)):
            e = OxmlElement(f'w:{k}'); e.set(qn('w:w'), str(v)); e.set(qn('w:type'), 'dxa'); m.append(e)
        tcPr.append(m)
    def nosplit(row): row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
    def run(p, text, bold=False, size=None, color=None, italic=False, fill=None):
        r = p.add_run(text); r.bold = bold; r.italic = italic
        if size: r.font.size = Pt(size)
        if color: r.font.color.rgb = rgb(color)
        if fill:
            sh = OxmlElement('w:shd'); sh.set(qn('w:val'), 'clear'); sh.set(qn('w:color'), 'auto'); sh.set(qn('w:fill'), fill); r._r.get_or_add_rPr().append(sh)
        return r
    def para(text='', bold=False, size=None, color=None, after=5, italic=False, align=None):
        p = d.add_paragraph(); p.paragraph_format.keep_with_next = True; run(p, text, bold, size, color, italic); p.paragraph_format.space_after = Pt(after)
        if align: p.alignment = align
        return p
    def bullet(text, lead=None):
        p = d.add_paragraph(style='List Bullet'); p.paragraph_format.space_after = Pt(3)
        if lead: run(p, lead + ' ', bold=True)
        run(p, text)
    def spacer(pt=4):
        p = d.add_paragraph(); p.paragraph_format.space_after = Pt(0); p.paragraph_format.line_spacing = Pt(pt)
    cnt = [0]
    def h1(text):
        cnt[0] += 1
        p = d.add_paragraph(); p.paragraph_format.space_before = Pt(16); p.paragraph_format.space_after = Pt(8); p.paragraph_format.keep_with_next = True
        run(p, f'{cnt[0]:02d}', bold=True, size=11, color=AMBER); run(p, '   ' + text, bold=True, size=17, color=NAVY)
        b = OxmlElement('w:pBdr'); bt = OxmlElement('w:bottom')
        bt.set(qn('w:val'), 'single'); bt.set(qn('w:sz'), '8'); bt.set(qn('w:space'), '4'); bt.set(qn('w:color'), AMBER); b.append(bt); p._p.get_or_add_pPr().append(b)
    def h2(text):
        p = d.add_paragraph(); p.paragraph_format.space_before = Pt(8); p.paragraph_format.keep_with_next = True; run(p, text, bold=True, size=12, color=NAVY)
    def table(header, data, widths, aligns=None, colorcol=None):
        t = d.add_table(rows=1, cols=len(header)); t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.autofit = False
        for i, h in enumerate(header):
            c = t.rows[0].cells[i]; c.text = ''; shade(c, NAVY); margins(c, 70, 70, 110, 110); borders(c)
            p = c.paragraphs[0]; run(p, h, bold=True, size=8.5, color='FFFFFF'); p.paragraph_format.space_after = Pt(0); p.paragraph_format.keep_with_next = True
            if aligns and aligns[i] == 'r': p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for ri, row in enumerate(data):
            cells = t.add_row().cells
            for i, v in enumerate(row):
                c = cells[i]; c.text = ''; margins(c, 55, 55, 110, 110); c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER; borders(c, bottom=(4, LINE))
                if ri % 2: shade(c, SOFT)
                p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(0)
                if ri == 0: p.paragraph_format.keep_with_next = True
                col = colorcol[1](str(v)) if colorcol and i == colorcol[0] else None
                run(p, str(v), bold=(i == 0 or col is not None), size=9, color=col or INK)
                if aligns and aligns[i] == 'r': p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for row in t.rows:
            nosplit(row)
            for i, w in enumerate(widths): row.cells[i].width = Cm(w)
        spacer(6)
    def finding(f):
        fg, bg = TAGS[f['tag']]; t = d.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.rows[0].cells[0]; shade(c, SOFT); borders(c, left=(36, fg)); margins(c, 110, 110, 220, 160); c.text = ''
        p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(3); run(p, f' {f["tag"]} ', bold=True, size=8, color=fg, fill=bg); run(p, '  ' + f['title'], bold=True, size=11, color=NAVY)
        p2 = c.add_paragraph(); p2.paragraph_format.space_after = Pt(0); run(p2, f['text'], size=10)
        if f.get('extra'):
            p3 = c.add_paragraph(); p3.paragraph_format.space_before = Pt(3); p3.paragraph_format.space_after = Pt(0); run(p3, f['extra'], size=9, color=MUT, italic=True)
        nosplit(t.rows[0]); spacer(7)
    def callout(title, text, fill='EFF6FF', fg='1D4ED8'):
        t = d.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER; c = t.rows[0].cells[0]; shade(c, fill); borders(c); margins(c, 110, 110, 180, 180); c.text = ''
        p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(0); run(p, title.upper() + '   ', bold=True, size=8.5, color=fg); run(p, text, size=10); nosplit(t.rows[0]); spacer(7)
    def picture(path, w, cap):
        p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after = Pt(2); p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(path, width=Cm(w)); para(cap, size=8.5, color=MUT, after=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    fig = [0]
    def figcap(t): fig[0] += 1; return f'Рис. {fig[0]}. {t}'
    cf = lambda v: ('B91C1C' if float(v) < 1.0 else 'B45309' if float(v) < 1.8 else '047857')

    # footer
    fp = s0.footer.paragraphs[0]; run(fp, f'Аудит рекламного кабінету · {M["client"]} · {M["period"]}', size=8, color=MUT)
    fp.add_run('\t'); fp.paragraph_format.tab_stops.add_tab_stop(Cm(17.2), alignment=2)
    r_ = fp.add_run(); r_.font.size = Pt(8); r_.font.color.rgb = rgb(MUT)
    for typ, txt in (('begin', None), (None, 'PAGE'), ('end', None)):
        if typ: e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), typ)
        else: e = OxmlElement('w:instrText'); e.set(qn('xml:space'), 'preserve'); e.text = txt
        r_._r.append(e)

    # cover
    t = d.add_table(rows=1, cols=1); t.alignment = WD_TABLE_ALIGNMENT.CENTER; c = t.rows[0].cells[0]; shade(c, NAVY); borders(c, bottom=(48, AMBER)); margins(c, 380, 380, 400, 400); c.text = ''
    p = c.paragraphs[0]; run(p, 'АУДИТ РЕКЛАМНОГО КАБІНЕТУ META ADS', bold=True, size=9, color=AMBER); p.paragraph_format.space_after = Pt(10)
    p = c.add_paragraph(); run(p, M['client'], bold=True, size=30, color='FFFFFF'); p.paragraph_format.space_after = Pt(6)
    p = c.add_paragraph(); run(p, f'Період аналізу: {M["period"]}  ·  Витрати в {cur}  ·  {K["n_act"]} кампаній з витратами', size=10.5, color='CBD5E1'); p.paragraph_format.space_after = Pt(0)
    spacer(10)

    def kpi_row(items):
        t = d.add_table(rows=1, cols=len(items)); t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.autofit = False
        for i, (lab, val, sub, col) in enumerate(items):
            c = t.rows[0].cells[i]; shade(c, SOFT); borders(c, top=(24, col), left=(12, 'FFFFFF'), right=(12, 'FFFFFF')); margins(c, 120, 120, 150, 120); c.width = Cm(17.2 / len(items)); c.text = ''
            p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(1); run(p, lab.upper(), bold=True, size=7.5, color=MUT)
            p = c.add_paragraph(); p.paragraph_format.space_after = Pt(1); run(p, val, bold=True, size=19, color=NAVY)
            p = c.add_paragraph(); p.paragraph_format.space_after = Pt(0); run(p, sub, size=8, color=MUT)
        spacer(6)
    kpi_row([('Витрати', f'{sym}{K["spend"]:,.0f}', M['period'], 'F59E0B'), ('Покупки', f'{K["purchases"]:,.0f}', f'ціна покупки {sym}{K["cpa"]:.2f}' if K['cpa'] else '', '0EA5E9'),
             ('Цінність покупок', f'{sym}{K["value"]:,.0f}', 'за даними пікселя', '10B981'), ('ROAS', f'{roas:.2f}', 'цінність покупок / витрати', '8B5CF6')])
    kpi_row([('CPM', f'{sym}{K["cpm"]:.2f}', 'ціна 1000 показів', '0EA5E9'), ('CTR за посиланням', f'{K["ctr"]:.2f}%', 'кліки / покази', '10B981'),
             ('Частота головної', f'{K["top_freq"]:.1f}', 'накопичена за період', 'EF4444'), ('Порожніх кампаній', f'{K["zero"]} з {K["n_all"]}', 'без витрат за період', 'F59E0B')])

    # 1 findings
    h1('Ключові знахідки')
    para('Знахідки впорядковані за впливом. Мітки: КРИТИЧНО (діяти зараз), УВАГА (ризик), ІНСАЙТ (що показують дані), МОЖЛИВІСТЬ (де є запас росту). Усе нижче рахується з цифр експорту; гіпотези позначені.', size=10, color=MUT)
    for f in rep['findings']: finding(f)

    # 2 structure
    h1('Структура акаунта')
    table(['Показник', 'Значення', 'Що це означає'], [
        ['Кампаній усього', str(K['n_all']), 'за весь час існування акаунта'], ['З витратами за період', str(K['n_act']), f'{K["n_act"] / K["n_all"] * 100:.0f}% акаунта'],
        ['Без витрат', str(K['zero']), 'кандидати на архівацію'], ['Активні зараз', str(K['active_now']), 'працюють у період аналізу']] +
        ([[a['name'], f'{sym}{a["spend"]:,.0f}', f'ROAS {a["roas"]:.2f}'] for a in rep['audience_types']] if rep['audience_types'] else []), [5.2, 3.6, 8.4], ['l', 'l', 'l'])

    # 3 campaigns
    h1('Кампанії за бюджетом')
    c_ = rep['campaigns']
    picture(hbar([x['name'][:34] for x in c_], [x['spend'] for x in c_], 'spend.png', f'Витрати, {cur}', fmt=sym + '{:,.0f}'), 15.2, figcap('Розподіл витрат за кампаніями'))
    table(['Кампанія', 'Стан', 'Витрати', 'Покупки', 'Ціна', 'ROAS', 'Част.', 'CTR'],
          [[x['name'][:36], x['state'], f'{sym}{x["spend"]:,.0f}', f'{x["pur"]:.0f}', f'{sym}{x["cpa"]:.2f}' if x['cpa'] else '—', f'{x["roas"]:.2f}', f'{x["freq"]:.1f}', f'{x["ctr"]:.2f}%'] for x in c_],
          [5.4, 1.9, 1.7, 1.6, 1.5, 1.4, 1.3, 1.4], ['l', 'l', 'r', 'r', 'r', 'r', 'r', 'r'], colorcol=(5, cf))
    picture(hbar([x['name'][:34] for x in c_], [x['roas'] for x in c_], 'roas.png', 'ROAS (пунктир: середній по акаунту)', gc, ref=roas), 15.2, figcap('ROAS кампаній'))

    if rep['ads']:
        h1('Креативи')
        table(['Оголошення', 'Стан', 'Витрати', 'Покупки', 'ROAS', 'Част.', 'Якість', 'Конверсія'],
              [[a['name'][:34], a['state'], f'{sym}{a["spend"]:,.0f}', f'{a["pur"]:.0f}', f'{a["roas"]:.2f}', f'{a["freq"]:.1f}', a['quality'], a['conv']] for a in rep['ads']],
              [4.6, 1.9, 1.7, 1.6, 1.4, 1.3, 2.2, 2.5], ['l', 'l', 'r', 'r', 'r', 'r', 'l', 'l'], colorcol=(4, cf))
        para('Якість і конверсія: рейтинги Meta відносно конкурентів на тих самих показах. «—» означає, що рейтингу немає.', size=9, color=MUT)
    if rep['placements']:
        h1('Плейсменти'); pl = rep['placements']
        picture(hbar([x['name'] for x in pl], [x['roas'] for x in pl], 'placement.png', 'ROAS за плейсментами (пунктир: середній)', gc, ref=roas), 15.2, figcap('ROAS за плейсментами'))
        table(['Плейсмент', 'Витрати', 'Частка', 'Покупки', 'Ціна', 'ROAS', 'CTR'],
              [[x['name'], f'{sym}{x["spend"]:,.0f}', f'{x["share"]:.0f}%', f'{x["pur"]:.0f}', f'{sym}{x["cpa"]:.2f}' if x['cpa'] else '—', f'{x["roas"]:.2f}', f'{x["ctr"]:.2f}%'] for x in pl],
              [4.4, 2.0, 1.8, 2.0, 2.0, 1.8, 1.8], ['l', 'r', 'r', 'r', 'r', 'r', 'r'], colorcol=(5, cf))
        para('Плейсменти з витратами менше 5 не показані. Малі вибірки дають напрям для тесту, а не висновок.', size=9, color=MUT)
    if rep['ages']:
        h1('Аудиторія: вік і стать'); ag = rep['ages']
        picture(hbar([x['name'] for x in ag], [x['roas'] for x in ag], 'age.png', 'ROAS за віком (пунктир: середній)', gc, ref=roas), 15.2, figcap('ROAS за віком'))
        table(['Вік', 'Витрати', 'Частка', 'Покупки', 'Ціна', 'ROAS'], [[x['name'], f'{sym}{x["spend"]:,.0f}', f'{x["share"]:.0f}%', f'{x["pur"]:.0f}', f'{sym}{x["cpa"]:.2f}' if x['cpa'] else '—', f'{x["roas"]:.2f}'] for x in ag],
              [3.2, 2.4, 2.2, 2.4, 2.4, 2.4], ['l', 'r', 'r', 'r', 'r', 'r'], colorcol=(5, cf))
        if rep['female_share'] is not None: para(f'Жінки: {rep["female_share"]:.0f}% витрат.', size=10)
    if rep['trend']:
        h1('Динаміка'); t_ = rep['trend']
        table(['Період', 'Витрати', 'ROAS'], [['Попередні 14 днів', f'{sym}{t_["spend_prev"]:,.0f}', f'{t_["roas_prev"]:.2f}'], ['Останні 14 днів', f'{sym}{t_["spend_last"]:,.0f}', f'{t_["roas_last"]:.2f}']], [6, 4, 4], ['l', 'r', 'r'])
    if rep['funnel']:
        h1('Воронка')
        table(['Етап', 'Кількість', 'Конверсія з попереднього'], [[x['stage'], f'{x["value"]:,.0f}', f'{x["conv"]:.1f}%' if x['conv'] is not None else '—'] for x in rep['funnel']], [6, 4, 6], ['l', 'r', 'r'])
    if rep['site_rows']:
        h1('Посадкова сторінка')
        src = 'PageSpeed Insights' if rep['site_source'] == 'pagespeed' else 'замір у браузері, одне завантаження'
        para(f'Джерело замірів: {src}. З експорту не видно, куди саме ведуть оголошення: перевірте адресу посадкової в самих оголошеннях.', size=10, color=MUT)
        sc = lambda v: '047857' if v in ('добре', 'ок') else 'B91C1C' if v.startswith(('критично', 'повільно', 'слабко')) else 'B45309'
        table(['Перевірка', 'Результат', 'Оцінка'], rep['site_rows'], [5.4, 6.4, 5.4], ['l', 'l', 'l'], colorcol=(2, sc))
    if rep['breakeven']:
        h1('Беззбитковий ROAS'); b = rep['breakeven']
        para(f'При маржі {b["margin"]}% до реклами беззбитковий ROAS {b["roas_be"]:.2f}. Поточний {b["roas"]:.2f}: акаунт {"у плюсі" if b["ok"] else "у мінусі"}.', size=10)
        table(['Маржа до реклами', 'Беззбитковий ROAS', 'Стан'], [[f'{m}%', f'{100 / m:.2f}', 'у плюс' if roas > 100 / m else 'у мінус'] for m in (70, 60, 50, 40, 30)], [5.5, 5.5, 6.2], ['l', 'r', 'l'],
              colorcol=(2, lambda v: '047857' if v == 'у плюс' else 'B91C1C'))
    h1('Пріоритети')
    table(['№', 'Дія', 'Очікуваний ефект (гіпотеза)', 'Терміновість'], [[str(i), p['action'], p['effect'], p['urgency']] for i, p in enumerate(rep['priorities'], 1)], [0.9, 7.8, 5.8, 2.7], ['l', 'l', 'l', 'l'])
    h1('Межі аудиту')
    for x in rep['limits']: bullet(x)
    if rep['missing']:
        h2('Що додати для глибшого аудиту')
        for x in rep['missing']: bullet(x)

    out = os.path.join(cfg['_base'], cfg.get('output', 'audit.docx')); d.save(out); print('Збережено', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True); a = ap.parse_args()
    build(with_defaults(load_config(a.config)))
