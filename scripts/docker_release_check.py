"""Offline validation for the standalone Telegram/GHCR release.
Does not require a Telegram token or contact Telegram.
"""
from pathlib import Path
import importlib
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
required = [
    'Dockerfile', 'compose.yaml', '.dockerignore', '.gitignore',
    '.github/workflows/publish-ghcr.yml', '.env.example',
    'app/main.py', 'app/telegram_adapter.py', 'app/semantic_knowledge.py',
    'data/semantic_topics.json', 'data/seed_faq.json', 'assets/bot_welcome.png'
]
for f in required:
    assert (ROOT / f).is_file(), f'Missing required file: {f}'

# These files must never be in the distributable/repository root.
for name in ['.env', 'runtime/bot.sqlite3', 'runtime/knowledge_base.json']:
    assert not (ROOT / name).exists(), f'Sensitive runtime file present: {name}'

source = (ROOT / 'app/main.py').read_text(encoding='utf-8')
dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
assert 'TelegramAdapter' in source
assert 'python", "-m", "app.main' in dockerfile
assert '/app/runtime' in compose
assert 'TELEGRAM_BOT_TOKEN' in (ROOT / '.env.example').read_text(encoding='utf-8')
assert re.search(r'VERSION\s*=\s*[\'\"]1\.0\.4(?:-tg)?[\'\"]', (ROOT / 'app/version.py').read_text(encoding='utf-8'))
for mod in ['app.main', 'app.telegram_adapter', 'app.semantic_knowledge']:
    importlib.import_module(mod)
print('DOCKER RELEASE SOURCE CHECK: PASS')
