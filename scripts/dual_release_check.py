"""No-network checks for combined GitHub/GHCR release."""
from pathlib import Path
import ast
import importlib
import re
import sys
import subprocess
import yaml

ROOT=Path(__file__).resolve().parents[1]
# A local ignored .env/runtime is allowed in Codespaces; it must never be Git-tracked.
if (ROOT/'.env').exists():
    if not (ROOT/'.git').exists():
        raise AssertionError('Do not distribute .env in ZIP')
    p=subprocess.run(['git','ls-files','--error-unmatch','.env'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    assert p.returncode != 0, '.env must not be tracked'
for dirname in ['bots/zvezdochka', 'bots/tourist']:
    assert not list((ROOT/dirname).rglob('*.sqlite3')), 'SQLite application data must not ship'

assert not list(ROOT.rglob('*.ttf')), 'Font binaries are not part of this release'
c=yaml.safe_load((ROOT/'compose.yaml').read_text(encoding='utf-8'))
expected={'zvezdochka','tourist','caddy'}
assert set(c['services']) == expected
z=c['services']['zvezdochka']; t=c['services']['tourist']
assert z['environment']['TELEGRAM_BOT_TOKEN'] != t['environment']['BOT_TOKEN']
assert 'ZVEZDOCHKA_BOT_TOKEN' in z['environment']['TELEGRAM_BOT_TOKEN']
assert 'TOURIST_BOT_TOKEN' in t['environment']['BOT_TOKEN']
assert 'env_file' not in z and 'env_file' not in t, 'Never expose the other bot token'
assert z['volumes'] == ['zvezdochka_runtime:/app/runtime']
assert 'tourist_runtime:/app/runtime' in t['volumes']
assert t['environment']['DATABASE_PATH'] == '/app/runtime/tourist.sqlite3'
assert 'WEBAPP_URL' in t['environment'] and 'TOURIST_DOMAIN' in t['environment']['WEBAPP_URL']
assert c['services']['caddy']['depends_on']['tourist']['condition']=='service_healthy'
assert 'reverse_proxy tourist:8000' in (ROOT/'Caddyfile').read_text(encoding='utf-8')
for name in ('zvezdochka','tourist'):
    p=ROOT/'bots'/name
    assert (p/'Dockerfile').is_file()
    assert (p/'app/main.py').is_file()
    assert (p/'requirements.txt').is_file()
assert (ROOT/'bots/tourist/data/showcase_knowledge.json').exists()
docker_t=(ROOT/'bots/tourist/Dockerfile').read_text(encoding='utf-8')
assert 'COPY data/' in docker_t
assert 'USER 10001:10001' in docker_t
assert 'COPY web/' in docker_t
for path in (ROOT/'bots/tourist/app').glob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'))
for fn in (ROOT/'bots/tourist/scripts/verify_telegram.py',ROOT/'bots/tourist/app/notifications.py',ROOT/'bots/tourist/app/bot.py'):
    assert 'api.telegram.org/bot' not in fn.read_text(encoding='utf-8'),f'Hardcoded Telegram URL: {fn}'
for item in ('bot.py','notifications.py'):
    assert 'telegram_transport' in (ROOT/'bots/tourist/app'/item).read_text(encoding='utf-8')
w=(ROOT/'.github/workflows/publish-ghcr.yml').read_text(encoding='utf-8')
assert 'needs: [tests]' in w and 'bots/zvezdochka' in w and 'bots/tourist' in w
assert 'zvezdochka-latest' in w and 'tourist-latest' in w
print('DUAL RELEASE SOURCE CHECK: PASS')
