"""Safe local backup status/check; never sends sensitive records to a network."""
import argparse
import json
from app.maintenance import backup_if_due, backup_status


def main(argv=None):
    parser = argparse.ArgumentParser(description='ТУРИСТ: состояние резервных копий')
    parser.add_argument('--run', action='store_true', help='Создать проверенную копию, если подошло время')
    args = parser.parse_args(argv)
    try:
        outcome = backup_if_due() if args.run else 'read-only'
        status = backup_status()
        print(json.dumps({'result':outcome, 'backup':status},ensure_ascii=False,indent=2))
        if args.run and outcome in ('disabled','no-database'):
            print('Копия не создана: отсутствует рабочий бот или база либо автоархивация выключена.')
            return 2
        return 0
    except Exception as exc:
        print('Ошибка сохранения: '+type(exc).__name__+'. Проверьте наличие места и доступ к папке backups.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
