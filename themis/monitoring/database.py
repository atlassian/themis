import threading
import json
import time
from sqlalchemy import Table, Column, Integer, String, Text, MetaData, ForeignKey, create_engine, select
from sqlalchemy.sql import and_, or_, not_
import themis.config
from themis.util.common import inject_env_vars

# global DB connection
DB_TABLE_HISTORY = 'states_history'
DB_TABLE_CONFIGS = 'configs'


class HistoricalState(object):
    def __init__(self, section, resource, state=None, action=None):
        self.timestamp = time.time() * 1000.0
        self.section = section
        self.resource = resource
        self.state = state or {}
        self.action = action


def get_states_table(metadata=None):
    if not metadata:
        metadata = MetaData()
    states_table = Table(DB_TABLE_HISTORY, metadata,
        Column('timestamp', String(20), primary_key=True),
        Column('section', String(30)),
        Column('resource', String(50)),
        Column('state', Text),
        Column('action', String(50))
    )
    return states_table


def get_config_table(metadata=None):
    if not metadata:
        metadata = MetaData()
    config_table = Table(DB_TABLE_CONFIGS, metadata,
        Column('section', String(30)),
        Column('resource', String(50)),
        Column('config', Text)
    )
    return config_table


def get_db_connection(db_url=None):
    local = threading.local()
    try:
        local.db_connections
    except AttributeError:
        local.db_connections = {}
    if not db_url:
        db_url = inject_env_vars(themis.config.get_value('db_url', config_file_only=True))
    db_connection = local.db_connections.get(db_url)
    if not db_connection:
        # create DB enging
        engine = create_engine(db_url)
        # create metadata
        metadata = MetaData()
        if not engine.dialect.has_table(engine, DB_TABLE_HISTORY):
            states_table = get_states_table(metadata)
            metadata.create_all(engine)
        if not engine.dialect.has_table(engine, DB_TABLE_CONFIGS):
            config_table = get_config_table(metadata)
            metadata.create_all(engine)
        db_connection = local.db_connections[db_url] = engine
    return db_connection


def history_add(section, resource, state, action):
    state = json.dumps(state)
    ms = time.time() * 1000.0
    db_connection = get_db_connection()
    conn = db_connection.connect()
    states_table = get_states_table()
    ins = states_table.insert()
    ins = ins.values(timestamp=ms, section=section, resource=resource, state=state, action=action)
    result = conn.execute(ins)
    state = HistoricalState(section, resource, state=state, action=action)
    return state


def history_get(section, resource, limit=100):
    states_table = get_states_table()
    stmt = select([states_table]).where(
        and_(
            states_table.c.section == section,
            states_table.c.resource == resource
        )
    ).order_by(states_table.c.timestamp.desc()).limit(limit)
    db_connection = get_db_connection()
    conn = db_connection.connect()
    rows = conn.execute(stmt).fetchall()
    result = [dict((states_table.columns.keys()[i], value)
                for i, value in enumerate(row)) for row in rows]
    for entry in result:
        if 'state' in entry:
            entry['state'] = json.loads(entry['state'])
    return result


def configs_fetch_all():
    config_table = get_config_table()
    stmt = select([config_table])
    db_connection = get_db_connection()
    conn = db_connection.connect()
    rows = conn.execute(stmt).fetchall()
    result = [dict((config_table.columns.keys()[i], value)
                for i, value in enumerate(row)) for row in rows]
    for entry in result:
        if 'config' in entry:
            entry['config'] = json.loads(entry['config'])
    return result


def config_save(section, resource, config):
    config_table = get_config_table()
    db_connection = get_db_connection()
    conn = db_connection.connect()
    # upsert config
    stmt = config_table.update().where(
        and_(
            config_table.c.section == section,
            config_table.c.resource == resource
        )
    ).values(section=section, resource=resource, config=config)
    result = conn.execute(stmt)
    # if no rows updated, then insert
    if result.rowcount <= 0:
        stmt = config_table.insert().values(section=section, resource=resource, config=config)
        result = conn.execute(stmt)
    return result
