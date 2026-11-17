"""Safely replace a clean SINGLE-BOT GitHub worktree with the TWO-BOT release.

Use from EXISTING repo root (tg-zvezda-promo):
  python3 _dual_import/scripts/migrate_existing_repo.py _dual_import

No commits/push; preserve .git and all untracked files (.env, live SQLite,
local secrets). Refuses changed tracked files and untracked path collisions.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def git(*args):
    result = subprocess.run(['git', *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode('utf-8', errors='replace').strip()

def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 _dual_import/scripts/migrate_existing_repo.py _dual_import')
    repo = Path.cwd().resolve()
    incoming = (repo / sys.argv[1]).resolve()
    if incoming == repo or not incoming.is_relative_to(repo):
        raise SystemExit('[STOP] Source must be an extracted folder INSIDE the repository.')
    if not incoming.is_dir() or not (incoming/'bots/zvezdochka/Dockerfile').exists() or not (incoming/'bots/tourist/Dockerfile').exists():
        raise SystemExit('[STOP] Wrong archive: expected complete two-bot release in _dual_import.')
    if Path(git('rev-parse', '--show-toplevel')).resolve() != repo:
        raise SystemExit('[STOP] Run from the root of the existing GitHub repository.')
    if git('branch', '--show-current') != 'main':
        raise SystemExit('[STOP] Switch to main first.')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('[STOP] There are uncommitted tracked changes. Commit/stash first. Nothing changed.')
    if not (repo/'app/telegram_adapter.py').exists():
        raise SystemExit('[STOP] Expected standalone Zvezdochka Telegram repository. Nothing changed.')
    tracked = {p for p in git('ls-files').splitlines() if p}
    if '.env' in tracked or any(x.startswith('runtime/') or x.startswith('secrets/') for x in tracked):
        raise SystemExit('[STOP] Sensitive files are tracked in Git. Handle them manually.')
    incoming_files=[p for p in incoming.rglob('*') if p.is_file()]
    for p in incoming_files:
        rel=p.relative_to(incoming)
        dest=repo/rel
        if rel.parts[0] == '.git':
            raise SystemExit('[STOP] Archive contains .git')
        if dest.exists() and rel.as_posix() not in tracked and not dest.samefile(p):
            # No overwrite of pre-existing untracked paths.
            raise SystemExit(f'[STOP] Untracked file would be overwritten: {rel}')
    name='backup-before-dual-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    git('branch', name)
    print('[OK] Backup Git branch:',name)
    for x in sorted(tracked):
        path=repo/x
        if path.is_file() or path.is_symlink():
            path.unlink()
    for src in incoming_files:
        rel=src.relative_to(incoming)
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
    print('[OK] Replaced tracked files; preserved .git, .env and untracked runtime.')
    print('[NEXT] rm -rf _dual_import')
    print('[NEXT] python3 scripts/dual_release_check.py')
    print('[NEXT] git status; git add -A; git diff --cached --name-only')
    print('[IMPORTANT] No commit or push performed; inspect changes first.')

if __name__ == '__main__':
    main()
