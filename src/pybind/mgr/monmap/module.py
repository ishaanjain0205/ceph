import json
from nvmeof.gateway.spdk.scripts.genrpc import schema
from pybind.mgr.mgr_module import CLICommandBase, Option
import time
import errno
import logging
import sqlite3
from collections import deque
from dataclasses import dataclass, astuple
from threading import Thread, Lock, Condition
from typing import Any, List, Literal, Optional

from .cli import MonMapCLICommand

from mgr_module import MgrModule, Option, NotifyType

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class MonInfoEntry:
    """Represents a single monitor's dump"""
    rank: int
    name: str
    public_addrs: dict[str, Any]
    addr: str
    public_addr: str
    priority: int
    weight: float
    time_added: str
    crush_location: dict[str, str]
    
    @classmethod
    def from_dict(cls, mon_info: dict[str, Any]):
        return MonInfoEntry(
            rank=mon_info["rank"],
            name=mon_info["name"],
            public_addrs=mon_info.get("public_addrs", {}),
            addr=mon_info["addr"],
            public_addr=mon_info["public_addr"],
            priority=mon_info["priority"],
            weight=mon_info["weight"],
            time_added=mon_info["time_added"],
            crush_location=mon_info.get('crush_location', {})
        )

@dataclass(frozen=True)  # 'frozen' makes it immutable and thread-safe
class MonMapEntry:
    """Represents an entire MonMap Snapshot"""
    epoch: int 
    fsid: str
    modified: str
    created: str
    min_mon_release: int
    min_mon_release_name: str
    election_strategy: int
    disallowed_leaders: str
    stretch_mode: bool
    tiebreaker_mon: str
    removed_ranks: str
    persistent_features: List[str]
    optional_features: List[str]
    mons: list[MonInfoEntry]
    num_mons: int
    
    @classmethod
    def from_dict(cls, mon_map: dict):
        mons_info_list=[
            MonInfoEntry.from_dict(mon_info) for mon_info in mon_map.get("mons", [])
        ]

        return MonMapEntry(
            epoch=mon_map["epoch"],
            fsid=mon_map["fsid"],
            modified=mon_map.get("modified", ""),
            created=mon_map.get("created", ""),
            min_mon_release=mon_map.get("min_mon_release", 0),
            min_mon_release_name=mon_map.get("min_mon_release_name", ""),
            election_strategy=mon_map.get("election_strategy", 0),
            disallowed_leaders=mon_map.get("disallowed_leaders", []),
            stretch_mode=mon_map.get("stretch_mode", False),
            tiebreaker_mon=mon_map.get("tiebreaker_mon", ""),
            removed_ranks=mon_map.get("removed_ranks", []),
            persistent_features=mon_map.get("persistent_features", []),
            optional_features=mon_map.get("optional_features", []),
            mons=mons_info_list,
            num_mons=len(mons_info_list),
        )

    def to_sqlite_tuple(self) -> tuple:
        """
        Returns the data in the exact order required by the
        INSERT statement.
        """
        return astuple(self)


class Module(MgrModule):
    CLICommand: CLICommandBase = MonMapCLICommand
    MODULE_OPTIONS: List[Option] = []
    NOTIFY_TYPES = [NotifyType.mon_map]
    MON_AUDIT_CMD_NS = '.mon.ns' # QUESTION

    MODULE_OPTIONS: List[Option] = [
        {
            "name": "retention_days",
            "type": "int",
            "default": 30,
            "desc": "Maximum age of audit records in days",
            "runtime": True,
        },
        {
            "name": "max_records",
            "type": "int",
            "default": 1000000,
            "desc": "Maximum number of records to keep in the database",
            "runtime": True,
        },
    ]

    def serve(self):
        # removed pruning
        #_do_serve() ??
    
    @MonMapCLICommand.Read('audit fetch')
    def audit_fetch(self,
                    limit: Optional[int] = 100,
                    entity: Optional[str] = None):
        return self.show_audit_records(limit, entity)

    def show_audit_records(self, limit, entity) -> tuple[Literal[0], str, Literal['']] | tuple[int, Literal[''], str]:
        query = """
        SELECT timestamp, user, user_host, entity_name, command,
        args, retval, sequence, epoch, state FROM audit_commands """
        params = []

        if entity:
            query += "WHERE entity_name LIKE ? "
            params.append(f"%{entity}%")
        query += "ORDER BY epoch DESC, sequence DESC LIMIT ?"
        params.append(limit)
        try:
            with self.conn_lock:
                cursor = self.dbconn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = [
                    {
                        "timestamp": r[0],
                        "user": r[1],
                        "user_host": r[2],
                        "entity_name": r[3],
                        "command": r[4],
                        "args": r[5],
                        "retval": r[6],
                        "state": r[9]
                    } for r in rows
                ]
                return (0, json.dumps(results, indent=2), "")
        except Exception as e:
            return (-errno.EINVAL, "", f"Failed to query audit database: {e}")

    def notify(self, notify_type: NotifyType, notify_id: str) -> None:
        log.debug(f'notify_type={notify_type}')
        if not notify_type == 'mon_map':
            return
        mon_map = self.get('mon_map')
        entry = MonMapEntry.from_dict(mon_map)
        with self.qlock:
            self.q.append(entry.to_sqlite_tuple())
            self.qcond.notify_all()

    def audit_recorder(self):


        INSERT_MON_MAP = '''INSERT INTO mon_map(
            epoch, fsid, modified, created, min_mon_release, 
            min_mon_release_name, election_strategy,
            stretch_mode, tiebreaker_mon, num_mons)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);'''

        INSERT_MONITOR = '''INSERT INTO monitors(
            rank, name, addr, public_addr, priority, weight, 
            time_added, epcoh)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?);'''
        
        # TO DO: Implement logic to push to queue given 2 different types of 
        # insert queries
        try:
            self.qlock.acquire()
            while not self.stopping:
                while not len(self.q):
                    log.debug('audit queue empty')
                    self.qcond.wait_for(lambda: len(self.q), timeout=1)
                log.debug(f'have {len(self.q)} audit records')
                audit_recs = list(self.q)
                self.q.clear()
                self.qlock.release()
                log.debug(f'recording {len(audit_recs)} audit records')
                with self.conn_lock:
                    try:
                        self.dbconn.execute("BEGIN")
                        self.dbconn.executemany(INSERT_AUDIT, audit_recs)
                        self.dbconn.commit()
                    except Exception as e:
                        log.error(f'exception: {e}')
                    finally:
                        self.dbconn.rollback()
                        self.qlock.acquire()
        except Exception as e:
            log.error(f'exception: {e}')

    def get_last_recorded_epoch(self):
        """
        Fetches the epoch from the very last row inserted into the database.
        """
        # Using 'rowid' is an optimization in SQLite if you don't have
        # an explicit AUTOINCREMENT primary key.
        query = "SELECT epoch FROM audit_commands ORDER BY rowid DESC LIMIT 1"

        try:
            with self.conn_lock:
                cursor = self.dbconn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()

                if result is not None:
                    last_epoch = int(result[0])
                    log.info(f"Last recorded epoch found: {last_epoch}")
                    return last_epoch
                log.info("Audit table is empty. Starting fresh.")
                return 0
        except Exception as e:
            self.log.error(f"Error retrieving last recorded epoch: {e}")
            return 0

    def init_databases(self) -> None:
        CREATE_TABLES = ''' 
        CREATE TABLE IF NOT EXISTS mon_map_meta(
            key TEXT PRIMARY KEY,
            value NOT NULL
        ) WITHOUT ROWID;
        INSERT OR IGNORE INTO mon_map_meta (key, value) VALUES
            ('__db_version__', 1);
        CREATE TABLE IF NOT EXISTS mon_map (
            epoch INTEGER PRIMARY KEY,
            fsid TEXT NOT NULL,
            modified TEXT,
            created TEXT, 
            min_mon_release INTEGER,
            min_mon_release_name TEXT,
            election_strategy INTEGER,
            stretch_mode BOOLEAN,
            tiebreaker_mon TEXT,
            num_mons INTEGER
        );
        CREATE TABLE IF NOT EXISTS monitors (
            epoch INTEGER NOT NULL,
            name TEXT NOT NULL,
            rank INTEGER,
            addr TEXT,
            public_addr,
            prioirty INTEGER,
            weight REAL,
            time_added TEXT,
            PRIMARY KEY (epoch, name)
            FOREIGN KEY (epoch) REFRENCES mon_map(epoch)
        )
        '''

        # TO DO: update url to what?
        uri = f"file:///{self.AUDIT_POOL_NAME}:{self.MON_AUDIT_CMD_NS}/" \
            "audit_commands.db?vfs=ceph"
        log.debug(f'using uri: {uri}')

        self.conn_lock.acquire()
        try:
            db = sqlite3.connect(uri, check_same_thread=False, uri=True,
                                 isolation_level=None)
            db.execute('PRAGMA FOREIGN_KEYS = 1')
            db.execute('PRAGMA JOURNAL_MODE = PERSIST')
            db.execute('PRAGMA PAGE_SIZE = 65536')
            db.execute('PRAGMA CACHE_SIZE = 256')
            db.execute('PRAGMA TEMP_STORE = memory')
            db.executescript(CREATE_TABLES)
            self.dbconn = db
            log.debug('created tables')
        except Exception as e:
            log.error(f'exception: {e}')
        finally:
            self.conn_lock.release()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # audit queue
        self.dbconn = None
        self.qlock = Lock()
        self.conn_lock = Lock()
        self.qcond = Condition(self.qlock)
        self.stopping = False
        self.q = deque()

        # basic boilerplate...
        self.create_audit_pool()
        self.init_databases()

        # start record loop
        recorder = Thread(target=self.audit_recorder)
        recorder.start()

        # TODO: subscribe with last epoch. Note that ceph-mgr
        # already subscribes to log-info, but with starting
        # seq 0.
        self.get_last_recorded_epoch()

# TO DO:
# implement map class -> MonMap
# change notify() to get mon map from cluster and save persistently
    # write a querry function, that querries mon cluster, and maybe from native function
# create db schema for mon map
# method to write to db
# method to fetch from db


# todo to mon_map table
# add persistent features list
# add optional features list

# todo to monitor table
# add public addrs list
# add crush location list


CREATE_TABLES = '''
    CREATE TABLE IF NOT EXISTS mon_map (
        epoch INTEGER PRIMARY KEY,
        fsid TEXT NOT NULL,
        created TEXT, 
        min_mon_release INTEGER,
        min_mon_release_name TEXT,
        election_strategy INTEGER,
        stretch_mode BOOLEAN,
        tiebreaker_mon TEXT,
        num_mons INTEGER
    );
    CREATE TABLE IF NOT EXISTS monitors (
        epoch INTEGER NOT NULL,
        name TEXT NOT NULL,
        rank INTEGER,
        addr TEXT,
        prioirty INTEGER,
        weight REAL,
        time_added TEXT,
        PRIMARY KEY (epoch, name)
        FOREIGN KEY (epoch) REFRENCES mon_map(epoch)
    )
    '''

