"""Host protocol for an exported PG snapshot; subprocess failure never publishes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from scripts.recovery_facts import MAX_FACTS, validate


@contextmanager
def snapshot(command, log):
    code = Path(__file__).with_name('recovery_facts.py').read_text()
    with Path(log).open('ab') as errors:
        os.fchmod(errors.fileno(), 0o600)
        process = subprocess.Popen(command + ['python', '-c', code, '--hold'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
        try:
            output, deadline = bytearray(), time.monotonic() + 180
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while b'\n' not in output:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ValueError('Snapshot reader timed out.')
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk or len(output) + len(chunk) > MAX_FACTS + 1024:
                        raise ValueError('Snapshot reader failed or exceeded its bound.')
                    output.extend(chunk)
            result = json.loads(output)
            validate(result['facts'])
            import re
            if not isinstance(result['snapshot'], str) or not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', result['snapshot']):
                raise ValueError('Invalid exported snapshot identity.')
            yield result
            process.stdin.write(b'DUMP_COMPLETE\n')
            process.stdin.flush()
            if process.wait(timeout=15):
                raise ValueError('Snapshot reader did not finish successfully.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
