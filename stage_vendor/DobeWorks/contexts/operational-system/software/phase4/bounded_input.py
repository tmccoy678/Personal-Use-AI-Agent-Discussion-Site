"""Descriptor-confined, bounded reads shared by the synthetic cores."""

from __future__ import annotations

import os
import stat
from contextlib import ExitStack
from pathlib import Path


MAX_PATH_COMPONENTS = 128


class BoundedInputError(Exception):
    """A path or byte-bound failure with no accepted input bytes."""

    def __init__(self, message: str, limit_exceeded: bool = False) -> None:
        super().__init__(message)
        self.limit_exceeded = limit_exceeded


def _relative_parts(path, root: Path, root_alias) -> tuple:
    candidate = Path(path).absolute()
    for allowed in (root, root_alias):
        if allowed is None:
            continue
        try:
            parts = candidate.relative_to(allowed).parts
        except ValueError:
            continue
        if not parts or len(parts) > MAX_PATH_COMPONENTS or ".." in parts:
            raise BoundedInputError("input path has invalid or excessive components")
        return parts
    raise BoundedInputError("input path is outside its allowed root")


def read_regular(path, root: Path, root_identity: tuple, limit: int, root_alias=None) -> bytes:
    """Open from a pinned root, following no descendant symlink, then bound the read."""
    try:
        parts = _relative_parts(path, root, root_alias)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with ExitStack() as opened:
            directory = os.open(root, directory_flags)
            opened.callback(os.close, directory)
            observed = os.fstat(directory)
            if not stat.S_ISDIR(observed.st_mode) or (observed.st_dev, observed.st_ino) != root_identity:
                raise BoundedInputError("allowed input root identity changed")
            for component in parts[:-1]:
                directory = os.open(component, directory_flags, dir_fd=directory)
                opened.callback(os.close, directory)
            descriptor = os.open(parts[-1], file_flags, dir_fd=directory)
            opened.callback(os.close, descriptor)
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode):
                raise BoundedInputError("input path is not a regular file")
            if observed.st_size > limit:
                raise BoundedInputError("input exceeds its byte limit", limit_exceeded=True)
            with os.fdopen(descriptor, "rb", buffering=0, closefd=False) as stream:
                raw = bytearray()
                while len(raw) <= limit:
                    chunk = stream.read(min(65536, limit + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
            if len(raw) > limit or os.fstat(descriptor).st_size > limit:
                raise BoundedInputError("input exceeds its byte limit", limit_exceeded=True)
            return bytes(raw)
    except (AttributeError, NotImplementedError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise BoundedInputError("input path cannot be read safely") from error
