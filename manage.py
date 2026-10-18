#!/usr/bin/env python
import os
import sys
if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    from django.core.management import execute_from_command_line
    runtime = os.environ['DJANGO_SETTINGS_MODULE'] in ('config.settings.course_demo', 'config.settings.production')
    if runtime:
        from adc_core.operational_logging import SafeCommandErrors
        sys.stderr = SafeCommandErrors()
    try:
        execute_from_command_line(sys.argv)
    except SystemExit as exc:
        if runtime and exc.code not in (None, 0):
            sys.stderr.event('command.failed')
        raise
    except Exception:
        if not runtime:
            raise
        sys.stderr.event('command.failed')
        raise SystemExit(1) from None
