import threading
import sqlite3
import json
import time

# global DB connection
db_connection = None
DB_FILE_NAME = 'monitoring.data.db'


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
        c.execute('CREATE TABLE IF NOT EXISTS states ' +
            '(timestamp text unique, cluster text, state text, action text)')
        db_connection.commit()
    return db_connection


def history_add(cluster, state, action):
    nodes = state['nodes']
    state['nodes'] = {}
    del state['nodes_list']
    state['groups'] = {}
    for key, val in nodes.iteritems():
        instance_id = val['iid']
        group_id = val['gid']
        if group_id not in state['groups']:
            state['groups'][group_id] = {'instances': []}
        state['groups'][group_id]['instances'].append({
            'iid': val['iid']
            # TODO add more relevant data to persist
        })
    state = json.dumps(state)
    conn = history_get_db()
    c = conn.cursor()
    ms = time.time() * 1000.0
    c.execute("INSERT INTO states(timestamp,cluster,state,action) " +
        "VALUES (?,?,?,?)", (ms, cluster, state, action))
    conn.commit()


def history_get(cluster, limit=100):
    conn = history_get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM states WHERE cluster=? " +
        "ORDER BY timestamp DESC LIMIT ?", (cluster, limit))
    result = [dict((c.description[i][0], value)
                   for i, value in enumerate(row)) for row in c.fetchall()]
    for entry in result:
        if 'state' in entry:
            entry['state'] = json.loads(entry['state'])
    return result
