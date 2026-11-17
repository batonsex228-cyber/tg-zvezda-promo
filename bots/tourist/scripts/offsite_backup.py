"""Opt-in encrypted offsite SQLite snapshots for an S3-compatible object store.

Designed as a SEPARATE Docker Compose profile. Never sends plaintext SQLite,
BOT_TOKEN, a Google key, or the encryption passphrase to S3. Encryption is
performed locally by the already-tested AES-256-GCM snapshot exporter.

The object store and its credentials must be under the owner's control. Object
versioning/lifecycle and a recovery drill on a different machine are still
operational requirements, not guarantees provided by this script.
"""
import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.config import ROOT
from scripts.encrypted_backup import export_encrypted

STATE_NAME = '.offsite_last_success.json'


class OffsiteError(RuntimeError):
    """Deliberately credential-free failures."""


@dataclass(frozen=True)
class OffsiteConfig:
    bucket: str
    prefix: str = 'tourist/'
    region: str = ''
    endpoint_url: str = ''
    passphrase_file: str = ''
    interval_hours: int = 24

    @classmethod
    def from_environment(cls):
        raw_interval = os.getenv('OFFSITE_INTERVAL_HOURS', '24')
        try:
            interval = int(raw_interval)
        except ValueError:
            raise OffsiteError('OFFSITE_INTERVAL_HOURS должен быть целым числом.') from None
        return cls(
            bucket=os.getenv('OFFSITE_S3_BUCKET', '').strip(),
            prefix=os.getenv('OFFSITE_S3_PREFIX', 'tourist/').strip(),
            region=os.getenv('OFFSITE_S3_REGION', '').strip(),
            endpoint_url=os.getenv('OFFSITE_S3_ENDPOINT_URL', '').strip(),
            passphrase_file=os.getenv('OFFSITE_PASSPHRASE_FILE', '').strip(),
            interval_hours=interval,
        )

    def validate(self):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{2,62}', self.bucket):
            raise OffsiteError('Укажите допустимый OFFSITE_S3_BUCKET.')
        # The backup is placed ONLY under this literal prefix. Avoid ambiguous
        # key names and backslashes across providers.
        if (len(self.prefix) > 180 or not re.fullmatch(r'[a-zA-Z0-9_/-]+', self.prefix)
                or '..' in self.prefix or self.prefix.startswith('/')):
            raise OffsiteError('Некорректный OFFSITE_S3_PREFIX.')
        if not 1 <= self.interval_hours <= 24 * 30:
            raise OffsiteError('OFFSITE_INTERVAL_HOURS должен быть от 1 до 720.')
        if self.endpoint_url:
            try:
                uri = urlsplit(self.endpoint_url)
                port = uri.port
            except ValueError:
                raise OffsiteError('Некорректный OFFSITE_S3_ENDPOINT_URL.') from None
            if (uri.scheme != 'https' or not uri.hostname or uri.username or
                    uri.password or uri.path not in ('', '/') or uri.query or uri.fragment or
                    port not in (None, 443)):
                raise OffsiteError('S3 endpoint должен использовать HTTPS без путей и учётных данных.')
        if not self.passphrase_file:
            raise OffsiteError('Укажите OFFSITE_PASSPHRASE_FILE (отдельный файл секрета).')
        return self


def read_passphrase(path: str) -> str:
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise OffsiteError('Файл парольной фразы отсутствует или является символической ссылкой.')
    if p.stat().st_size > 4096:
        raise OffsiteError('Слишком большой файл парольной фразы.')
    try:
        text = p.read_text(encoding='utf-8').rstrip('\r\n')
    except (UnicodeError, OSError):
        raise OffsiteError('Не удалось безопасно прочитать парольную фразу.') from None
    if len(text) < 14 or '\n' in text or '\r' in text:
        raise OffsiteError('Парольная фраза должна быть одной строкой от 14 символов.')
    return text


def state_path(folder: Path) -> Path:
    return folder / STATE_NAME


def state_snapshot(folder: Path) -> dict:
    """Safe, non-secret operational summary for the owner Mini App."""
    try:
        data = json.loads(state_path(folder).read_text('utf-8'))
        at = data['uploaded_at']
        timestamp = datetime.fromisoformat(at)
        if timestamp.tzinfo is None:
            raise ValueError()
        hours = max(0., (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600)
        return {'last_verified_upload_at': at, 'age_hours': round(hours, 1),
                'present': True}
    except (KeyError, ValueError, TypeError, OSError, json.JSONDecodeError):
        return {'last_verified_upload_at': None, 'age_hours': None, 'present': False}


def save_state(folder: Path, uploaded_at: str, key: str, length: int, digest: str):
    """Publish success marker only AFTER S3 head_object has been verified."""
    folder.mkdir(parents=True, exist_ok=True)
    dest = state_path(folder)
    partial = folder / (STATE_NAME + '.tmp-' + uuid.uuid4().hex)
    payload = json.dumps({'uploaded_at': uploaded_at, 'object_key': key,
                          'size': length, 'sha256': digest}, ensure_ascii=False)
    try:
        fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, dest)
    finally:
        partial.unlink(missing_ok=True)


def _sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _s3_client(cfg: OffsiteConfig):
    try:
        import boto3
    except ImportError:
        raise OffsiteError('Отсутствует boto3: установите requirements.txt.') from None
    args = {}
    if cfg.region:
        args['region_name'] = cfg.region
    if cfg.endpoint_url:
        args['endpoint_url'] = cfg.endpoint_url
    return boto3.client('s3', **args)


def run_once(cfg: OffsiteConfig, *, s3=None, folder=None, now=None, force=False):
    """Back up, encrypt, upload, verify; never delete remote files automatically.

    A successful invocation publishes a local timestamp to avoid uploads on
    every sidecar restart. A failure leaves the success timestamp unchanged.
    """
    cfg.validate()
    folder = Path(folder) if folder is not None else ROOT / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        raise OffsiteError('Время запуска должно содержать часовой пояс.')
    status = state_snapshot(folder)
    if not force and status['present'] and status['age_hours'] is not None:
        uploaded = datetime.fromisoformat(status['last_verified_upload_at'])
        if current >= uploaded and (current - uploaded).total_seconds() < cfg.interval_hours * 3600:
            return 'up-to-date'
    # Verify encryption key availability BEFORE creating a plaintext snapshot.
    passphrase = read_passphrase(cfg.passphrase_file)
    client = s3 if s3 is not None else _s3_client(cfg)
    prefix = cfg.prefix.rstrip('/') + '/'
    stamp = current.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    key = f'{prefix}{stamp}-{uuid.uuid4().hex[:12]}.tbackup'
    # Encrypted and temporary snapshots are only ever stored under the private
    # backup volume; TemporaryDirectory cleans them up on upload failures.
    with tempfile.TemporaryDirectory(prefix='tourist-offsite-', dir=folder) as temp:
        encrypted = export_encrypted(Path(temp) / 'encrypted.tbackup', passphrase=passphrase)
        length = encrypted.stat().st_size
        digest = _sha256_file(encrypted)
        # AES-GCM protects the archive; server-side encryption protects the
        # stored object again on standard S3-compatible endpoints.
        client.upload_file(str(encrypted), cfg.bucket, key, ExtraArgs={
            'ContentType': 'application/octet-stream',
            'ServerSideEncryption': 'AES256',
            'Metadata': {'tourist-sha256': digest},
        })
        info = client.head_object(Bucket=cfg.bucket, Key=key)
        metadata = info.get('Metadata') or {}
        if (int(info.get('ContentLength', -1)) != length or
                metadata.get('tourist-sha256') != digest):
            raise OffsiteError('Проверка метаданных выгруженного объекта S3 не пройдена.')
        # An object-store HEAD response is not a byte-for-byte validation.
        # Download the encrypted object and verify the exact ciphertext bytes.
        # No decrypted personal information is ever downloaded from S3.
        remote_copy = Path(temp) / 'roundtrip.tbackup'
        client.download_file(cfg.bucket, key, str(remote_copy))
        if remote_copy.stat().st_size != length or _sha256_file(remote_copy) != digest:
            raise OffsiteError('Контрольная сумма загруженной обратно S3-копии не совпала.')
    save_state(folder, current.isoformat(timespec='seconds'), key, length, digest)
    return 'uploaded-and-download-verified'


def main(argv=None):
    parser = argparse.ArgumentParser(description='ТУРИСТ: зашифрованные внешние копии (S3)')
    parser.add_argument('mode', choices=('once', 'loop'))
    args = parser.parse_args(argv)
    # Never print exception text: S3 exceptions can include endpoint addresses,
    # request metadata or other operationally private values.
    try:
        cfg = OffsiteConfig.from_environment().validate()
        read_passphrase(cfg.passphrase_file)
        if args.mode == 'once':
            print('Offsite: ' + run_once(cfg), flush=True)
            return 0
        while True:
            try:
                print('Offsite: ' + run_once(cfg), flush=True)
            except Exception as exc:
                print('Offsite: failed (' + type(exc).__name__ + '); will retry.', flush=True)
            time.sleep(max(60, min(3600, cfg.interval_hours * 3600 // 4)))
    except Exception as exc:
        print('Offsite: setup failed (' + type(exc).__name__ + ').', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
