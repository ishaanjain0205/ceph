from dataclasses import dataclass
from typing import Optional
import sqlite3

@dataclass
class AuditQuery:
    # filters
    before_seq: Optional[int] = None
    after_seq: Optional[int] = None
    since: Optional[int] = None
    until: Optional[int] = None
    status: Optional[str] = None
    command: Optional[str] = None

    # ordering constraints
    order_by: str = "init_time"
    ascending: bool = False
    limit: int = 100

    # columns to return
    columns: Optional[list[str]] = None


DEFAULT_SELECT_COLS = [
    "seq", 
    "cmd", 
    "cmd_args", 
    "init_time", 
    "comp_time", 
    "status", 
    "retval"
]

# CUSTOM QUERRY FACTOR
def build_select_cols(cols: list[str]):
    return ", ".join(cols)

def build_select(q: AuditQuery):
    select_cols = None
    if not q.columns:
        select_cols = build_select_cols(DEFAULT_SELECT_COLS)
    else:
        select_cols = build_select_cols(q.columns)
    
    return select_cols

def build_where(q: AuditQuery):
    where = []
    params = []

    if q.before_seq is not None:
        where.append("seq < ?")
        params.append(q.before_seq)

    if q.after_seq is not None:
        where.append("seq > ?")
        params.append(q.after_seq)

    if q.since is not None:
        where.append("init_time >= ?")
        params.append(q.since)
    
    if q.until is not None:
        where.append("init_time <= ?")
        params.append(q.until)
    
    if q.status is not None:
        where.append("status = ?")
        params.append(q.status)

    if q.command is not None:
        where.append("cmd = ?")
        params.append(q.command)

    if not where and not params:
        return "", params
    
    return " WHERE " + " AND ".join(where), params

def build_order(q: AuditQuery):
    order = "ASC" if q.ascending else "DESC"
    return f"{q.order_by} {order}"

def build_query(q: AuditQuery, table_name: str):
    select_sql = build_select(q)
    where_sql, params = build_where(q)
    order_sql = build_order(q)

    sql = f"""SELECT {select_sql} FROM {table_name} {where_sql} ORDER BY {order_sql} LIMIT ?"""
    params.append(q.limit)

    return sql, params


def get_all_log_entries(conn, table_name):
    """Get all log entries sorted by descending init timestamps"""

    cmd = f"""
        SELECT seq, cmd, cmd_args, init_time, comp_time, status, retval
        FROM {table_name}
        ORDER BY init_time DESC
    """
    return conn.execute(cmd).fetchall()


def get_recent_commands_ran(conn, table_name):
    """Get all <command, init_time> entries sorted by descending init timestamps"""
    cmd = f"""
        SELECT cmd, init_time
        FROM {table_name}
        ORDER BY init_time DESC
    """
    return conn.execute(cmd).fetchall()


def get_logs_by_command(conn, command, table_name):
    """Get all log entries, filter by command, ordered by descending init_time"""
    cmd = f"""
        SELECT seq, cmd, cmd_args, init_time, comp_time, status, retval
        FROM {table_name}
        WHERE cmd = ?
        ORDER BY init_time DESC
    """
    return conn.execute(cmd, (command,)).fetchall()


def get_logs_by_status(conn, status, table_name):
    """Get all log entries filtered by status"""
    cmd = f"""
        SELECT seq, cmd, cmd_args, init_time, comp_time, status, retval
        FROM {table_name}
        WHERE status = ?
        ORDER BY init_time DESC
    """
    return conn.execute(cmd, (status,)).fetchall()


def get_logs_in_time_range(conn, since, until, table_name):
    """Get all log entries in specified [since, until] time range"""
    cmd = f"""
        SELECT seq, cmd, cmd_args, init_time, comp_time, status, retval
        FROM {table_name}
        WHERE init_time >= ? AND init_time <= ?
        ORDER BY init_time ASC
    """
    return conn.execute(cmd, (since, until,)).fetchall()


def get_logs_after_seq(conn, after_seq, table_name):
    """Get all log entries after a given sequence number ordered by ascending seqnumber"""
    sql = f"""
        SELECT seq, cmd, cmd_args, init_time, comp_time, status, retval
        FROM {table_name}
        WHERE seq > ?
        ORDER BY seq ASC
    """
    return conn.execute(sql, (after_seq,)).fetchall()

def get_logs_with_retval(conn, retval, table_name):
    """Get all log entries after a given sequence number ordered by ascending seqnumber"""
    sql = f"""
        SELECT seq, cmd, cmd_args, init_time, comp_time, status, retval
        FROM {table_name}
        WHERE retval = ?
        ORDER BY seq ASC
    """
    return conn.execute(sql, (retval,)).fetchall()

def main():
    #TODO: Define db conn
    #TODO: Execute on db logic
    pass

if __name__ == "__main__":
    main()

