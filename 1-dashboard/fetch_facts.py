"""Збір даних Meta Ads для дашборда-артефакта (токен лише ads_read).

Робить те саме, що «Пульт аналітики»: бере щоденні дані рівня «оголошення» по кожному
кліентському кабінету і пише їх у файли, які дашборд читає як набори даних:
  out/facts.json     рядок = день x оголошення: date, project, campaign, adset, ad,
                     spend, impressions, clicks, results, revenue
  out/projects.json  проєкти й цілі (з config.json)
  out/clients.json   клієнти (з config.json)

Токен береться зі змінної середовища META_TOKEN і нікуди не записується.
Скрипт лише читає дані з Meta, нічого в кабінетах не змінює.

Запуск:   python fetch_facts.py --config config.json --days 30 --out out
Без мережі (перевірка логіки): python fetch_facts.py --self-test
"""
import argparse, datetime as dt, json, os, sys, time, urllib.parse, urllib.request, urllib.error

API_VERSION = "v23.0"
FIELDS = "objective,date_start,campaign_name,adset_name,ad_name,spend,impressions,inline_link_clicks,results,actions,action_values"
# Яка дія Meta вважається «результатом» для типу проєкту (можна змінити в config.json -> result_action)
DEFAULT_ACTION = {"lead": "lead", "purchase": "purchase", "message": "onsite_conversion.messaging_conversation_started_7d"}
PURCHASE_ALIASES = ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def pick(items, name):
    """Значення з масиву actions/action_values за назвою дії."""
    names = PURCHASE_ALIASES if name == "purchase" else (name,)
    for n in names:
        for it in items or []:
            if it.get("action_type") == n:
                return _num(it.get("value"))
    return 0.0


# Мета кампанії Meta -> сімейство. У config.json -> "objectives": ["LEADS"] залишає в проєкті лише кампанії цих цілей:
# результати різних цілей (ліди, перегляди профілю, покупки) не можна складати в одну ціну результату.
FAMILY = {"OUTCOME_SALES": "SALES", "CONVERSIONS": "SALES", "PRODUCT_CATALOG_SALES": "SALES",
          "OUTCOME_LEADS": "LEADS", "LEAD_GENERATION": "LEADS",
          "OUTCOME_ENGAGEMENT": "ENGAGEMENT", "POST_ENGAGEMENT": "ENGAGEMENT", "MESSAGES": "ENGAGEMENT", "VIDEO_VIEWS": "ENGAGEMENT",
          "OUTCOME_TRAFFIC": "TRAFFIC", "LINK_CLICKS": "TRAFFIC",
          "OUTCOME_AWARENESS": "AWARENESS", "REACH": "AWARENESS", "BRAND_AWARENESS": "AWARENESS",
          "OUTCOME_APP_PROMOTION": "APP", "APP_INSTALLS": "APP"}


def http_get(url, fetcher=None, token=None):
    if fetcher:
        return fetcher(url)
    for attempt in range(4):
        try:
            headers = {"User-Agent": "toolkit-dashboard/1.0"}
            if token:
                headers["Authorization"] = "Bearer " + token  # токен у заголовку, не в адресі
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            body = raw[:300]
            try:
                err_code = json.loads(raw).get("error", {}).get("code")
            except ValueError:
                err_code = None
            if err_code in (4, 17, 32, 613) and attempt < 3:   # ліміт запитів Meta: чекаємо й повторюємо
                print(f"Ліміт запитів Meta, чекаю {60 * (attempt + 1)} с…", file=sys.stderr)
                time.sleep(60 * (attempt + 1))
                continue
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise SystemExit(f"Meta API відповіла {e.code}: {body}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(3)
                continue
            raise SystemExit(f"Немає зв'язку з Meta API: {e.reason}")


def fetch_account(account_id, since, until, token, fetcher=None):
    """Усі рядки insights рівня ad по днях за період, з пагінацією."""
    params = {
        "level": "ad", "time_increment": 1, "fields": FIELDS, "limit": 500,
        "time_range": json.dumps({"since": since, "until": until}),
    }
    url = f"https://graph.facebook.com/{API_VERSION}/{account_id}/insights?" + urllib.parse.urlencode(params)
    rows = []
    while url:
        data = http_get(url, fetcher, token)
        rows.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
    return rows


def fetch_account_info(account_id, token, fetcher=None):
    """Статус, валюта й часовий пояс кабінету (1 = активний, 9 = пільговий період оплати)."""
    url = f"https://graph.facebook.com/{API_VERSION}/{account_id}?" + urllib.parse.urlencode(
        {"fields": "account_status,currency,timezone_name"})
    return http_get(url, fetcher, token)


def api_results(row):
    """Поле results Insights API: той самий «Results», що в Ads Manager (залежить від оптимізації кампанії). None, якщо поля немає."""
    res = row.get("results")
    if not res:
        return None
    total = 0.0
    for item in res:
        vals = item.get("values") or []
        if vals:
            total += _num(vals[0].get("value"))
    return total


def to_fact(row, project, rtype, action, source="api"):
    results = api_results(row) if source == "api" else None
    if results is None:   # поля немає (наприклад, миттєві лід-форми) або обрано source=actions: дія за типом проєкту
        results = pick(row.get("actions"), action)
    revenue = pick(row.get("action_values"), "purchase") if rtype == "purchase" else 0.0
    return {
        "date": row["date_start"], "project": project,
        "campaign": row.get("campaign_name", ""), "adset": row.get("adset_name", ""), "ad": row.get("ad_name", ""),
        "spend": round(_num(row.get("spend")), 2), "impressions": int(_num(row.get("impressions"))),
        "clicks": int(_num(row.get("inline_link_clicks"))), "results": int(results), "revenue": round(revenue, 2),
    }


def build(config, days, token, fetcher=None, today=None):
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days - 1)).isoformat()
    until = today.isoformat()
    facts, projects, clients = [], [], []
    for c in config["clients"]:
        name, rtype = c["project"], c.get("type", "lead")
        action = c.get("result_action") or DEFAULT_ACTION.get(rtype, "lead")
        info = fetch_account_info(c["account_id"], token, fetcher)
        cur = info.get("currency", "USD")
        if cur != "USD":
            print(f"УВАГА: кабінет {name} у валюті {cur}. Дашборд показує знак $ і пороги в доларах: "
                  "переведіть пороги в page.html або використовуйте кабінет у USD.", file=sys.stderr)
        rows = fetch_account(c["account_id"], since, until, token, fetcher)
        want = {x.upper() for x in c.get("objectives", [])}
        if want:
            rows = [r for r in rows if FAMILY.get((r.get("objective") or "").upper(), "OTHER") in want or (r.get("objective") or "").upper() in want]
        facts.extend(to_fact(r, name, rtype, action, c.get("results_source", "api")) for r in rows)
        projects.append({"project": name, "type": rtype, "result_label": c.get("result_label", "Результати"),
                         "target_cpr": c.get("target_cpr", 0), "target_roas": c.get("target_roas", 0)})
        clients.append({"project": name, "status": c.get("status", "active"), "monthly_fee": c.get("monthly_fee", 0),
                        "client_since": c.get("client_since"), "until": c.get("until"),
                        "monthly_budget": c.get("monthly_budget", 0),
                        "account_status": int(info.get("account_status", 1))})
    facts.sort(key=lambda f: (f["date"], f["project"], f["campaign"], f["adset"], f["ad"]))
    return facts, projects, clients


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def self_test():
    """Перевірка без мережі: підставна відповідь Meta, дві сторінки."""
    pages = {
        0: {"data": [{"date_start": "2026-01-02", "campaign_name": "К1", "adset_name": "А1", "ad_name": "О1",
                      "spend": "10.50", "impressions": "1000", "inline_link_clicks": "20",
                      "actions": [{"action_type": "lead", "value": "3"}]}],
            "paging": {"next": "https://graph.facebook.com/next?p=2"}},
        1: {"data": [{"date_start": "2026-01-02", "campaign_name": "К2", "adset_name": "А2", "ad_name": "О2",
                      "spend": "40", "impressions": "5000", "inline_link_clicks": "50",
                      "actions": [{"action_type": "omni_purchase", "value": "2"}],
                      "action_values": [{"action_type": "omni_purchase", "value": "120.0"}]}]},
    }
    calls = []

    def fetcher(url):
        if "/insights" not in url and "next" not in url:
            return {"account_status": 9, "currency": "USD"}
        calls.append(url)
        return pages[len(calls) - 1 if len(calls) <= 2 else 1]

    cfg = {"clients": [{"project": "Тест", "account_id": "act_1", "type": "lead", "target_cpr": 5}]}
    facts, projects, _ = build(cfg, 7, "TOKEN", fetcher, today=dt.date(2026, 1, 3))
    assert len(calls) == 2 and "access_token" not in calls[0], "пагінація або токен в адресі"
    assert _[0]["account_status"] == 9, "статус кабінету"
    assert facts[0]["results"] == 3 and facts[0]["spend"] == 10.5 and facts[0]["clicks"] == 20, facts[0]
    r_api = {"date_start": "2026-01-02", "spend": "10", "impressions": "100", "inline_link_clicks": "5",
             "results": [{"indicator": "profile_visit_view", "values": [{"value": "77"}]}],
             "actions": [{"action_type": "lead", "value": "3"}]}
    assert to_fact(r_api, "T", "lead", "lead")["results"] == 77, "results з API"
    assert to_fact(r_api, "T", "lead", "lead", "actions")["results"] == 3, "results з actions"
    only = {"clients": [{"project": "Л", "account_id": "act_3", "type": "lead", "objectives": ["LEADS"]}]}
    mix = {"data": [dict(r_api, objective="OUTCOME_LEADS"), dict(r_api, objective="OUTCOME_TRAFFIC")]}
    f3, _, _ = build(only, 7, "TOKEN", lambda u: mix if "/insights" in u else {"account_status": 1, "currency": "USD"}, today=dt.date(2026, 1, 3))
    assert len(f3) == 1, "фільтр за ціллю"
    cfg2 = {"clients": [{"project": "Магазин", "account_id": "act_2", "type": "purchase"}]}
    calls.clear()
    f2, _, _ = build(cfg2, 7, "TOKEN", lambda u: pages[1], today=dt.date(2026, 1, 3))
    assert f2[0]["results"] == 2 and f2[0]["revenue"] == 120.0, f2[0]
    assert projects[0]["target_cpr"] == 5
    print("self-test ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", default="out")
    ap.add_argument("--only", help="узяти лише проєкт з такою назвою (для першої перевірки на одному кабінеті)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    token = os.environ.get("META_TOKEN")
    if not token:
        raise SystemExit("Задайте змінну середовища META_TOKEN (токен системного користувача, право ads_read).")
    if a.days < 1 or a.days > 90:
        raise SystemExit("--days має бути від 1 до 90")
    with open(a.config, encoding="utf-8") as f:
        config = json.load(f)
    if a.only:
        config = {"clients": [c for c in config["clients"] if c["project"] == a.only]}
        if not config["clients"]:
            raise SystemExit(f"У config.json немає проєкту «{a.only}»")
    facts, projects, clients = build(config, a.days, token)  # помилка тут не залишає напівзаписаних файлів
    os.makedirs(a.out, exist_ok=True)
    for name, obj in (("facts", facts), ("projects", projects), ("clients", clients)):
        tmp = os.path.join(a.out, name + ".json.tmp")
        write_json(tmp, obj)
        os.replace(tmp, os.path.join(a.out, name + ".json"))
    print(f"Готово: {len(facts)} рядків, {len(projects)} проєктів -> {a.out}")


if __name__ == "__main__":
    main()
