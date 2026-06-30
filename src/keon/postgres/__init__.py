"""PostgreSQL backup/restore command builders via Docker."""

from __future__ import annotations

import shlex

from keon.util import printcp

__all__ = [
    "build_pg_backup_cmd",
    "build_pg_restore_cmd",
    "print_backup_cmd",
    "print_restore_cmd",
]


def _q(value: object) -> str:
    """Shell-safe quoting for command arguments."""
    return shlex.quote(str(value))


def _normalize_backup_name(backup_name: str) -> str:
    """Ensure backup filename ends with ``.sql``."""
    if not backup_name.endswith(".sql"):
        backup_name += ".sql"
    return backup_name


def _get_backup_name(db_name: str, backup_name: str | None = None) -> str:
    """
    Resolve backup filename.

    When ``backup_name`` is None, ``db_name`` is used as the base name.

    Args:
        db_name: Database name.
        backup_name: Optional custom backup filename.

    Returns:
        Normalized backup filename ending with ``.sql``.
    """
    if backup_name is None:
        backup_name = db_name

    return _normalize_backup_name(backup_name)


def build_pg_backup_cmd(
    *,
    username: str,
    password: str,
    host: str,
    port: int | str,
    db_name: str,
    backup_name: str | None = None,
    image: str = "postgres:18-alpine",
) -> str:
    """
    Build a ``docker run`` command that dumps a PostgreSQL database to a local file.

    The dump is written to ``./<backup_name>`` in the current working directory
    (mounted as ``/dump`` inside the container).

    Args:
        username: PostgreSQL user.
        password: PostgreSQL password (passed via ``PGPASSWORD``).
        host: Database host reachable from the container.
        port: Database port.
        db_name: Database name to dump.
        backup_name: Output filename; defaults to ``db_name.sql``.
        image: Docker image providing ``pg_dump``.

    Returns:
        Single-line shell command string.

    Example:
        >>> cmd = build_pg_backup_cmd(
        ...     username='postgres', password='secret',
        ...     host='host.docker.internal', port=5432, db_name='mydb',
        ... )
        >>> 'pg_dump' in cmd and 'mydb.sql' in cmd
        True
    """
    backup_name = _get_backup_name(db_name, backup_name)

    return " ".join(
        [
            "docker run --rm",
            "-e",
            _q(f"PGPASSWORD={password}"),
            "-v",
            '"${PWD}:/dump"',
            _q(image),
            "pg_dump",
            "-U",
            _q(username),
            "-h",
            _q(host),
            "-p",
            _q(port),
            "-d",
            _q(db_name),
            "--no-owner",
            "--no-privileges",
            "-f",
            _q(f"/dump/{backup_name}"),
        ]
    )


def build_pg_restore_cmd(
    *,
    username: str,
    password: str,
    host: str,
    port: int | str,
    db_name: str,
    backup_name: str | None = None,
    image: str = "postgres:18-alpine",
) -> str:
    """
    Build a ``docker run`` command that restores a SQL dump into PostgreSQL.

    Expects ``./<backup_name>`` to exist in the current working directory
    (mounted as ``/dump`` inside the container).

    Args:
        username: PostgreSQL user.
        password: PostgreSQL password (passed via ``PGPASSWORD``).
        host: Database host reachable from the container.
        port: Database port.
        db_name: Target database name.
        backup_name: Dump filename; defaults to ``db_name.sql``.
        image: Docker image providing ``psql``.

    Returns:
        Single-line shell command string.

    Example:
        >>> cmd = build_pg_restore_cmd(
        ...     username='postgres', password='secret',
        ...     host='host.docker.internal', port=5432, db_name='mydb',
        ... )
        >>> 'psql' in cmd and 'ON_ERROR_STOP=1' in cmd
        True
    """
    backup_name = _get_backup_name(db_name, backup_name)

    return " ".join(
        [
            "docker run --rm",
            "-e",
            _q(f"PGPASSWORD={password}"),
            "-v",
            '"${PWD}:/dump"',
            _q(image),
            "psql",
            "-U",
            _q(username),
            "-h",
            _q(host),
            "-p",
            _q(port),
            "-d",
            _q(db_name),
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            _q(f"/dump/{backup_name}"),
        ]
    )


def print_backup_cmd(**kwargs) -> str:
    """
    Build a backup command, print it, and copy it to the clipboard.

    Args:
        **kwargs: Forwarded to :func:`build_pg_backup_cmd`.

    Returns:
        The generated command string.
    """
    cmd = build_pg_backup_cmd(**kwargs)
    printcp(cmd)
    return cmd


def print_restore_cmd(**kwargs) -> str:
    """
    Build a restore command, print it, and copy it to the clipboard.

    Args:
        **kwargs: Forwarded to :func:`build_pg_restore_cmd`.

    Returns:
        The generated command string.
    """
    cmd = build_pg_restore_cmd(**kwargs)
    printcp(cmd)
    return cmd
