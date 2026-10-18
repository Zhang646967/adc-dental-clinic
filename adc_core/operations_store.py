"""Bounded private operational files; checksums detect corruption, not authorship.

No application models, credentials, request bodies or arbitrary error strings.
Directory descriptors and no-follow opens keep all operations inside one private
directory. Writers serialize a complete state using replace, never a partial JSON.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

MAX_BYTES = 512 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate operational field.')
        result[name] = value
    return result


class PrivateStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or
                info.st_uid != os.geteuid()):
            raise ValueError('An owner-only operational directory is required.')

    @contextmanager
    def directory_fd(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_mode & 0o077 or info.st_uid != os.geteuid():
                raise ValueError('Operational directory ownership differs.')
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', value):
            raise ValueError('Invalid operational filename.')
        return value

    @staticmethod
    def check_file(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or
                info.st_uid != os.geteuid() or info.st_nlink != 1):
            raise ValueError('An owner-only regular operational file is required.')

    def read(self, name):
        with self.directory_fd() as folder:
            fd = os.open(self.name(name), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=folder)
            with os.fdopen(fd, 'rb') as stream:
                self.check_file(os.fstat(stream.fileno()))
                raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Operational file exceeds its bound.')
        try:
            obj = json.loads(raw, object_pairs_hook=_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite number.')))
        except RecursionError:
            raise ValueError('Operational nesting exceeds its bound.') from None
        if not isinstance(obj, dict) or set(obj) != {'payload', 'sha256'}:
            raise ValueError('Invalid operational envelope.')
        if hashlib.sha256(canonical(obj['payload'])).hexdigest() != obj['sha256']:
            raise ValueError('Operational checksum differs.')
        return obj['payload']

    def write(self, name, payload):
        raw = canonical({'payload': payload, 'sha256': hashlib.sha256(canonical(payload)).hexdigest()}) + b'\n'
        if len(raw) > MAX_BYTES:
            raise ValueError('Operational state exceeds its bound.')
        with self.directory_fd() as folder:
            name = self.name(name)
            try:
                self.check_file(os.stat(name, dir_fd=folder, follow_symlinks=False))
            except FileNotFoundError:
                pass
            temporary = 'tmp-' + uuid4().hex
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=folder)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
                os.fsync(folder)
            finally:
                try:
                    os.unlink(temporary, dir_fd=folder)
                except FileNotFoundError:
                    pass

    @contextmanager
    def lock(self, name):
        with self.directory_fd() as folder:
            fd = os.open(self.name(name), os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW,
                         0o600, dir_fd=folder)
            try:
                self.check_file(os.fstat(fd))
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                os.close(fd)

    def archive_monitor(self):
        """Explicit offline reset only; retain three bounded prior observations."""
        with self.directory_fd() as folder:
            for name in ('monitor.json','previous-1.json','previous-2.json','previous-3.json'):
                try:
                    info = os.stat(name, dir_fd=folder, follow_symlinks=False)
                    self.check_file(info)
                    if info.st_size > MAX_BYTES:
                        raise ValueError('Oversized evidence requires private manual investigation.')
                except FileNotFoundError:
                    pass
            for original, saved in (('previous-2.json','previous-3.json'),
                                    ('previous-1.json','previous-2.json'),
                                    ('monitor.json','previous-1.json')):
                try:
                    os.replace(original, saved, src_dir_fd=folder, dst_dir_fd=folder)
                except FileNotFoundError:
                    pass
            os.fsync(folder)
