"""Encrypted portable SQLite snapshots for manually moving to offsite storage.

AES-256-GCM over a WAL-safe, independently validated SQLite snapshot; key derived
with Scrypt + random salt. A passphrase is NEVER accepted on the command line.
Never restores over the live DATABASE_PATH or an existing file.

Format: MAGIC(12) | SALT(16) | NONCE(12) | AES-GCM ciphertext | TAG(16)
All header bytes are authenticated as associated data.
"""
import argparse
import getpass
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from app.database import database_path
from scripts.backup_db import create_backup
from scripts.restore_check import verify_backup
from scripts.recover_to_new_db import check_identity
from app.config import settings

MAGIC = b'TOURIST-ENC1'  # 12 bytes
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
BLOCK_BYTES = 1024 * 1024


class EncryptedBackupError(ValueError):
    pass


def _derive(passphrase: str, salt: bytes) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < 14:
        raise EncryptedBackupError('Парольная фраза должна содержать минимум 14 символов.')
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode('utf-8'))


def _exclusive(path: Path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')


def _backup_work_dir():
    from app.config import ROOT
    folder = ROOT / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def export_encrypted(destination, *, passphrase):
    """Export verified snapshot as encrypted file; refuse overwrite or symlinks."""
    dest = Path(destination).expanduser().absolute()
    if dest.suffix.lower() != '.tbackup':
        raise EncryptedBackupError('Зашифрованная копия должна иметь расширение .tbackup')
    if dest.exists() or dest.is_symlink():
        raise FileExistsError('Файл назначения уже существует')
    if not dest.parent.is_dir():
        raise FileNotFoundError('Папка назначения не существует')
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    key = _derive(passphrase, salt)
    head = MAGIC + salt + nonce
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(head)
    temp = dest.with_name(dest.name + '.partial')
    if temp.exists() or temp.is_symlink():
        raise FileExistsError('Промежуточный файл уже существует')
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='tourist-export-', dir=_backup_work_dir()) as tmp:
            snapshot = create_backup(tmp)
            verify_backup(snapshot)
            with _exclusive(temp) as encrypted, snapshot.open('rb') as plaintext:
                created = True
                encrypted.write(head)
                while chunk := plaintext.read(BLOCK_BYTES):
                    encrypted.write(cipher.update(chunk))
                encrypted.write(cipher.finalize())
                encrypted.write(cipher.tag)
                encrypted.flush()
                os.fsync(encrypted.fileno())
        # Copy with exclusive creation: supports Windows USB/exFAT drives where
        # hard links are unavailable. Never replace another process's file.
        published = False
        try:
            with _exclusive(dest) as out, temp.open('rb') as inp:
                published = True
                shutil.copyfileobj(inp, out, length=BLOCK_BYTES)
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            if published:
                dest.unlink(missing_ok=True)
            raise
        temp.unlink()
        return dest
    except BaseException:
        if created:
            temp.unlink(missing_ok=True)
        raise


def import_encrypted(source, destination, *, passphrase, bot_token=None):
    """Restore encrypted archive into a *new* SQLite file, never the live DB."""
    src = Path(source).expanduser().resolve()
    dest = Path(destination).expanduser().absolute()
    if not src.is_file():
        raise FileNotFoundError('Зашифрованная копия не найдена')
    if dest.suffix.lower() != '.sqlite3':
        raise EncryptedBackupError('Восстановленная база должна иметь расширение .sqlite3')
    if dest.resolve() == database_path():
        raise EncryptedBackupError('Нельзя восстанавливать поверх рабочей базы')
    if dest.exists() or dest.is_symlink():
        raise FileExistsError('Файл назначения уже существует')
    if not dest.parent.is_dir():
        raise FileNotFoundError('Папка назначения не существует')
    with src.open('rb') as stream:
        head = stream.read(len(MAGIC) + SALT_BYTES + NONCE_BYTES)
        if len(head) != len(MAGIC) + SALT_BYTES + NONCE_BYTES or not head.startswith(MAGIC):
            raise EncryptedBackupError('Некорректный формат зашифрованной копии')
    salt, nonce = head[len(MAGIC):len(MAGIC)+SALT_BYTES], head[-NONCE_BYTES:]
    key = _derive(passphrase, salt)
    payload_bytes = src.stat().st_size - len(head) - TAG_BYTES
    if payload_bytes < 100:
        raise EncryptedBackupError('Файл зашифрованной копии неполный')
    # Create new target exclusively and delete it on any failed authentication,
    # DB validation or wrong-bot identity check.
    created = False
    try:
        with src.open('rb') as inp:
            inp.seek(-TAG_BYTES, os.SEEK_END)
            tag = inp.read(TAG_BYTES)
            inp.seek(len(head))
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(head)
            with _exclusive(dest) as out:
                created = True
                remain = payload_bytes
                while remain:
                    chunk = inp.read(min(BLOCK_BYTES, remain))
                    if not chunk:
                        raise EncryptedBackupError('Зашифрованная копия оборвана')
                    out.write(decryptor.update(chunk))
                    remain -= len(chunk)
                try:
                    out.write(decryptor.finalize())
                except InvalidTag:
                    raise EncryptedBackupError('Неверный пароль или повреждённая копия') from None
                out.flush()
                os.fsync(out.fileno())
        counts = verify_backup(dest)
        identity = check_identity(dest, settings.bot_token if bot_token is None else bot_token)
        return {'file': str(dest), 'counts': counts, 'identity': identity}
    except BaseException:
        if created:
            dest.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='ТУРИСТ: шифрованная переносимая резервная копия')
    commands = parser.add_subparsers(dest='mode', required=True)
    export = commands.add_parser('export', help='Создать копию .tbackup из текущей рабочей базы')
    export.add_argument('destination')
    restore = commands.add_parser('import', help='Восстановить архив в новый SQLite-файл')
    restore.add_argument('source')
    restore.add_argument('destination')
    args = parser.parse_args(argv)
    password = getpass.getpass('Парольная фраза (НЕ сохраняется): ')
    if args.mode == 'export':
        repeat = getpass.getpass('Повторите парольную фразу: ')
        if password != repeat:
            print('Парольные фразы не совпадают.')
            return 1
    try:
        if args.mode == 'export':
            export_encrypted(args.destination, passphrase=password)
            print('Шифрованная копия создана. Храните пароль ОТДЕЛЬНО от файла. Передача в облако выполняется вручную.')
        else:
            import_encrypted(args.source, args.destination, passphrase=password)
            print('Копия восстановлена в НОВЫЙ файл SQLite. Рабочая база и .env не изменены.')
        return 0
    except (OSError, sqlite3.DatabaseError, RuntimeError, EncryptedBackupError) as exc:
        print('Ошибка: ' + ('неверный пароль, повреждение или некорректные параметры.' if isinstance(exc, EncryptedBackupError)
                           else type(exc).__name__ + '. Проверьте права, место и резервную копию.'))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
