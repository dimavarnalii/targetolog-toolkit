"""Весь процес однією командою.

  python run_audit.py --config config.json                 # збір (API) -> сайт -> аналіз -> Word
  python run_audit.py --config config.json --skip-fetch    # дані вже в data/ (ручний експорт)
  python run_audit.py --config config.json --skip-fetch --skip-site
"""
import argparse, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument('--config', required=True)
ap.add_argument('--skip-fetch', action='store_true'); ap.add_argument('--skip-site', action='store_true')
a = ap.parse_args()
steps = []
if not a.skip_fetch: steps.append(['fetch_meta.py'])
if not a.skip_site: steps.append(['site_check.py'])
steps += [['analyze.py'], ['build_docx.py']]
for s in steps:
    print('==>', s[0])
    r = subprocess.run([sys.executable, os.path.join(here, s[0]), '--config', a.config] + s[1:])
    if r.returncode and s[0] != 'site_check.py':
        sys.exit(f'Крок {s[0]} завершився з помилкою')
print('Готово. Перевірте висновки перед відправкою клієнту.')
