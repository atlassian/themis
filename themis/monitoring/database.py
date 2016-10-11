import threading
import sqlite3
import json
import time

# global DB connection
db_connection = None
DB_FILE_NAME = 'monitoring.data.db'
DB_TABLE_HISTORY = 'states_history'


# TODO needed?
class HistoricalState(object):
    def __init__(self, section, resource, state=None, action=None):
        self.timestamp = time.time() * 1000.0
        self.section = section
        self.resource = resource
        self.state = state or {}
        self.action = action


def history_get_db():
    local = threading.local()
    db_connection = None
    try:
        db_connection = local.db_connection
    except AttributeError:
        pass
    if not db_connection:
        db_connection = sqlite3.connect(DB_FILE_NAME)
        local.db_connection = db_connection
        c = db_connection.cursor()
        c.execute(('CREATE TABLE IF NOT EXISTS %s ' +
            '(timestamp text unique, section text, resource text, state text, action text)')
            % DB_TABLE_HISTORY)
        db_connection.commit()
    return db_connection


def history_add(section, resource, state, action):
    state = json.dumps(state)
    conn = history_get_db()
    c = conn.cursor()
    ms = time.time() * 1000.0
    c.execute(("INSERT INTO %s(timestamp,section,resource,state,action) " +
        "VALUES (?,?,?,?,?)") % DB_TABLE_HISTORY, (ms, section, resource, state, action))
    conn.commit()


def history_get(section, resource, limit=100):
    conn = history_get_db()
    c = conn.cursor()
    c.execute(("SELECT * FROM %s WHERE section=? AND resource=? ORDER BY timestamp " +
        "DESC LIMIT ?") % DB_TABLE_HISTORY, (section, resource, limit))
    result = [dict((c.description[i][0], value)
                   for i, value in enumerate(row)) for row in c.fetchall()]
    for entry in result:
        if 'state' in entry:
            entry['state'] = json.loads(entry['state'])
    return result
