from sqlalchemy import create_engine, event

from database import (
    _configure_database_timezone,
    _set_mysql_session_timezone,
)


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.closed = False

    def execute(self, statement):
        self.statements.append(statement)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance


def test_mysql_session_timezone_is_forced_to_utc():
    connection = FakeConnection()

    _set_mysql_session_timezone(connection, None)

    assert connection.cursor_instance.statements == ["SET time_zone = '+00:00'"]
    assert connection.cursor_instance.closed


def test_timezone_listener_is_only_registered_for_mysql():
    mysql_engine = create_engine("mysql+pymysql://user:password@localhost/database")
    sqlite_engine = create_engine("sqlite:///:memory:")

    _configure_database_timezone(mysql_engine)
    _configure_database_timezone(sqlite_engine)

    assert event.contains(
        mysql_engine,
        "connect",
        _set_mysql_session_timezone,
    )
    assert not event.contains(
        sqlite_engine,
        "connect",
        _set_mysql_session_timezone,
    )


if __name__ == "__main__":
    test_mysql_session_timezone_is_forced_to_utc()
    test_timezone_listener_is_only_registered_for_mysql()
    print("database timezone tests passed")
