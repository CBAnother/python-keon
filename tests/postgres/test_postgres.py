"""Tests for postgres module."""

from unittest.mock import patch

import keon.postgres as kp
from keon.postgres import (
    build_pg_backup_cmd,
    build_pg_restore_cmd,
    print_backup_cmd,
    print_restore_cmd,
)

CONN = dict(
    username="postgres",
    password="p@ss w0rd",
    host="host.docker.internal",
    port=5432,
    db_name="mydb",
)


def test_q_quotes_special_chars():
    assert kp._q("hello") == "hello"
    assert kp._q("p@ss w0rd") == "'p@ss w0rd'"


def test_normalize_backup_name_adds_sql_suffix():
    assert kp._normalize_backup_name("dump") == "dump.sql"
    assert kp._normalize_backup_name("dump.sql") == "dump.sql"


def test_get_backup_name_defaults_to_db_name():
    assert kp._get_backup_name("mydb") == "mydb.sql"
    assert kp._get_backup_name("mydb", "custom") == "custom.sql"


def test_build_pg_backup_cmd_contains_expected_parts():
    cmd = build_pg_backup_cmd(**CONN)
    assert cmd.startswith("docker run --rm")
    assert "pg_dump" in cmd
    assert "--no-owner" in cmd
    assert "--no-privileges" in cmd
    assert "/dump/mydb.sql" in cmd
    assert "'PGPASSWORD=p@ss w0rd'" in cmd


def test_build_pg_backup_cmd_custom_backup_name():
    cmd = build_pg_backup_cmd(**CONN, backup_name="backup.sql")
    assert "/dump/backup.sql" in cmd


def test_build_pg_backup_cmd_custom_image():
    cmd = build_pg_backup_cmd(**CONN, image="postgres:16")
    assert "postgres:16" in cmd


def test_build_pg_restore_cmd_contains_expected_parts():
    cmd = build_pg_restore_cmd(**CONN)
    assert cmd.startswith("docker run --rm")
    assert " psql " in f" {cmd} "
    assert "ON_ERROR_STOP=1" in cmd
    assert "/dump/mydb.sql" in cmd


def test_build_pg_restore_cmd_custom_backup_name():
    cmd = build_pg_restore_cmd(**CONN, backup_name="restore.dump.sql")
    assert "/dump/restore.dump.sql" in cmd


@patch("keon.postgres.printcp")
def test_print_backup_cmd(mock_printcp):
    cmd = print_backup_cmd(**CONN)
    assert "pg_dump" in cmd
    mock_printcp.assert_called_once_with(cmd)


@patch("keon.postgres.printcp")
def test_print_restore_cmd(mock_printcp):
    cmd = print_restore_cmd(**CONN)
    assert "psql" in cmd
    mock_printcp.assert_called_once_with(cmd)
