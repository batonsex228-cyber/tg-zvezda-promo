"""Read-only Google Sheets connectivity test for a client-owned service account.

No rows or tabs are created, edited, cleared or deleted. The spreadsheet ID,
file path, service-account email, access tokens, and exception details never
appear in stdout or the JSON report. This is NOT a write-permission test.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.config import settings
from app.sheets import credentials_path


class GoogleCheckError(RuntimeError):
    pass


def validate_credentials_file(path):
    if path is None:
        raise GoogleCheckError('Укажите GOOGLE_CREDENTIALS_FILE в .env.')
    path = Path(path)
    # A maximum size catches accidental file path mixups and avoids processing
    # enormous or unexpected files while testing with elevated deployment rights.
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise GoogleCheckError('Файл Google-ключа отсутствует либо недопустим.')
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeError, ValueError, OSError):
        raise GoogleCheckError('Google-ключ не является корректным JSON-файлом.') from None
    if not isinstance(document, dict) or document.get('type') != 'service_account':
        raise GoogleCheckError('Нужен JSON-ключ сервисного аккаунта Google.')
    if not all(isinstance(document.get(k), str) and document[k].strip()
               for k in ('client_email', 'private_key', 'token_uri')):
        raise GoogleCheckError('В JSON-ключе отсутствуют необходимые поля.')
    url = urlsplit(document['token_uri'])
    if url.scheme != 'https' or url.netloc != 'oauth2.googleapis.com' or url.path != '/token' or url.query or url.fragment:
        raise GoogleCheckError('Некорректный адрес выдачи токенов в Google-ключе.')
    return True


def check_google_online(*, config=None, path=None, client_factory=None):
    """Check credentials and spreadsheet metadata only; return non-secret flags.

    The gspread client factory may be injected for isolated automated tests.
    """
    cfg = settings if config is None else config
    report = {'configured': bool(cfg.google_sheet_id and cfg.google_credentials_file),
              'credentials_valid': False, 'spreadsheet_readable': False,
              'write_permission_verified': False, 'status': 'not_configured'}
    if not report['configured']:
        return report
    try:
        validate_credentials_file(credentials_path() if path is None else path)
        report['credentials_valid'] = True
        if client_factory is None:
            import gspread
            client_factory = gspread.service_account
        client = client_factory(filename=str(credentials_path() if path is None else path))
        book = client.open_by_key(cfg.google_sheet_id)
        # Ask only for spreadsheet metadata. Do NOT download personal data or
        # modify any cells. The result is intentionally not exposed to caller.
        book.worksheets()
        report['spreadsheet_readable'] = True
        report['status'] = 'read_only_ok'
    except Exception:
        # Exception text from Google may contain tokens, IDs and other private
        # operational details. Deliberately return only the stage of failure.
        report['status'] = ('connection_failed' if report['credentials_valid']
                            else 'credentials_invalid')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='ТУРИСТ: только чтение метаданных Google Sheets')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    result = check_google_online()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        messages = {'not_configured':'Google Sheets не настроены.',
                    'credentials_invalid':'Проверьте файл ключа Google.',
                    'connection_failed':'Не удалось прочитать метаданные таблицы: проверьте сеть, доступ и библиотеки.',
                    'read_only_ok':'Метаданные таблицы прочитаны. Права на ЗАПИСЬ ещё не проверены.'}
        print('[GOOGLE CHECK] ' + messages[result['status']])
    return 0 if result['status'] == 'read_only_ok' else (2 if result['status'] == 'not_configured' else 1)


if __name__ == '__main__':
    raise SystemExit(main())
