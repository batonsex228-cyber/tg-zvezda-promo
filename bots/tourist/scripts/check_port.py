"""Offline readiness check: make sure the Mini App server port isn't occupied."""
from app.runtime import assert_port_free, StartupError


def main():
    try:
        assert_port_free()
    except StartupError as error:
        print('[ERROR]', error)
        return 1
    print('[OK] Порт 8000 свободен. Можно запускать «Турист».')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
