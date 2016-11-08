import threading
import subprocess32 as subprocess
import os
import re
import time
import urllib
import glob
import json
import math
import uuid
import logging
import decimal
import pyhive.presto
from datetime import datetime, timedelta
from collections import namedtuple

CACHE_CLEAN_TIMEOUT = 60 * 5
CACHE_MAX_AGE = 60 * 60
CACHE_FILE_PATTERN = '/tmp/cache.*.json'

# connect timeout for curl commands
CURL_CONNECT_TIMEOUT = 3

# cache query results
QUERY_CACHE_TIMEOUT = 60
GANGLIA_CACHE_TIMEOUT = 60
STATIC_INFO_CACHE_TIMEOUT = 60 * 30

# cache globals
last_cache_clean_time = 0
mutex_clean = threading.RLock()
mutex_popen = threading.RLock()


def get_logger(name=None):
    log = logging.getLogger(name)
    return log

# logger
LOG = get_logger(__name__)


class FuncThread(threading.Thread):
    def __init__(self, func, params, quiet=False):
        threading.Thread.__init__(self)
        self.daemon = True
        self.params = params
        self.func = func
        self.quiet = quiet

    def run(self):
        try:
            self.func(self.params)
        except Exception, e:
            if not self.quiet:
                print("Thread run method %s(%s) failed: %s" %
                    (self.func, self.params, traceback.format_exc()))

    def stop(self, quiet=False):
        if not quiet and not self.quiet:
            print("WARN: not implemented: FuncThread.stop(..)")


def clean_cache():
    global last_cache_clean_time
    mutex_clean.acquire()
    try:
        time_now = now()
        if last_cache_clean_time > time_now - CACHE_CLEAN_TIMEOUT:
            return
        for cache_file in set(glob.glob(CACHE_FILE_PATTERN)):
            mod_time = os.path.getmtime(cache_file)
            if time_now > mod_time + CACHE_MAX_AGE:
                os.remove(cache_file)
        last_cache_clean_time = time_now
    finally:
        mutex_clean.release()


def setup_logging(log_file=None, format='%(asctime)s %(levelname)s: %(name)s: %(message)s'):
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    if log_file:
        logging.basicConfig(filename=log_file, level=logging.INFO, format=format)
        formatter = logging.Formatter(format)
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
    else:
        logging.basicConfig(level=logging.INFO, format=format)


def now():
    return time.mktime(datetime.now().timetuple())


def json_namedtuple(json_string):
    return json.loads(json_string, object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))


def load_json_file(file, default=None):
    if not os.path.isfile(file):
        return default
    f = open(file)
    result = json.loads(f.read())
    f.close()
    return result


def save_file(file, content):
    f = open(file, 'w+')
    f.write(content)
    f.close()


def save_json_file(file, content):
    save_file(file, json.dumps(content))


def json_defaults(obj):
    if isinstance(obj, decimal.Decimal):
        if obj % 1 > 0:
            return float(obj)
        else:
            return long(obj)
    if isinstance(obj, datetime):
        TIMESTAMP_FORMAT_MS = '%Y-%m-%dT%H:%M:%S.%fZ'
        return obj.strftime(TIMESTAMP_FORMAT_MS)
    return obj


def json_fix(data):
    """
    Fix common JSON encoding issues. E.g., if a dict contains decimal.Decimal
    values, it cannot be dumped as JSON. This method creates a copy of the given
    dict and returns a cleaned-up version that should be JSON serializable.
    """
    return json.loads(json.dumps(data, default=json_defaults))


def is_composite(o):
    return isinstance(o, list) or isinstance(o, dict)


def is_float(f):
    return isinstance(f, float) and not math.isnan(f)


def remove_lines_from_string(s, regex):
    return '\n'.join([line for line in s.split('\n') if not re.match(regex, line)])


def is_number(s):
    try:
        float(s)
        return True
    except Exception:
        return False


def is_ip_address(s):
    return re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', s)


def is_NaN(obj, expect_only_numbers=False):
    if expect_only_numbers and not is_number(obj):
        return True
    if obj == 'NaN' or (isinstance(obj, float) and
            math.isnan(obj) or obj in [float('Inf'), -float('Inf')]):
        return True
    return False


def remove_NaN(obj, delete_values=True, replacement='NaN', expect_only_numbers=False):
    if isinstance(obj, list):
        i = 0
        while i < len(obj):
            if is_composite(obj[i]):
                remove_NaN(obj[i], delete_values, replacement, expect_only_numbers)
            elif is_NaN(obj[i], expect_only_numbers):
                if delete_values:
                    del obj[i]
                    i -= 1
                else:
                    obj[i] = replacement
            i += 1
    elif isinstance(obj, dict):
        for key in list(obj.keys()):
            if is_composite(obj[key]):
                remove_NaN(obj[key], delete_values, replacement, expect_only_numbers)
            elif is_NaN(obj[key], expect_only_numbers):
                if delete_values:
                    del obj[key]
                else:
                    obj[key] = replacement
    return obj


def short_uid():
    return str(uuid.uuid4())[0:8]


def inject_aws_endpoint(cmd):
    try:
        if not os.environ.AWS_ENDPOINT_URL:
            return cmd
        regex = r'^aws ([^\s]+) ([^\s]+)(.*)$'
        if re.match(regex, cmd):
            cmd = re.sub(regex, r'aws --endpoint-url="%s/\1/\2" \1 \2\3' % os.environ.AWS_ENDPOINT_URL, cmd)
    except AttributeError, e:
        pass
    return cmd


def inject_env_vars(s):
    regex = r'\$([a-zA-Z0-9_]+)'
    match = re.search(regex, s, re.MULTILINE)
    while match:
        var_name = match.group(1)
        s = s.replace('$%s' % var_name, os.environ.get(var_name, ''))
        match = re.search(regex, s, re.MULTILINE)
    return s


def run_func(func, cache_duration_secs=0, **kwargs):
    return run_cached(func, cache_duration_secs=cache_duration_secs, **kwargs)


def run_cached(func, cache_duration_secs=0, **kwargs):
    if cache_duration_secs <= 0:
        return func(**kwargs)
    hash = md5(func.__name__ + str(kwargs))
    cache_file = CACHE_FILE_PATTERN.replace('*', '%s') % hash
    if os.path.isfile(cache_file):
        # check file age
        mod_time = os.path.getmtime(cache_file)
        time_now = now()
        if mod_time > (time_now - cache_duration_secs):
            f = open(cache_file)
            result = f.read()
            f.close()
            return result
    result = func(**kwargs)
    f = open(cache_file, 'w+')
    if not isinstance(result, basestring):
        try:
            result = json.dumps(result)
        except Exception, e:
            result = json_fix(result)
            result = json.dumps(result)
    f.write(result)
    f.close()
    clean_cache()
    return result


def run(cmd, cache_duration_secs=0, log_error=False, retries=0, sleep=2, backoff=1.4):
    def do_run(cmd):
        try:
            mutex_popen.acquire()
            # process = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
            process = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            mutex_popen.release()
            output = ''
            for line in iter(process.stdout.readline, ''):
                output += line
            out, err = process.communicate()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd, output=output)
            return output
        except subprocess.CalledProcessError, e:
            if log_error:
                LOG.error("%s" % e.output)
            if retries > 0:
                LOG.info("INFO: Re-running command '%s'" % cmd)
                time.sleep(sleep)
                return run(cmd, cache_duration_secs, log_error, retries - 1, sleep * backoff, backoff)
            raise e
    cmd = inject_aws_endpoint(cmd)
    kwargs = {'cmd': cmd}
    return run_cached(do_run, cache_duration_secs=cache_duration_secs, **kwargs)


def md5(string):
    import hashlib
    m = hashlib.md5()
    m.update(string)
    return m.hexdigest()


def array_reverse(array):
    result = []
    for i, item1 in enumerate(array):
        for j, item2 in enumerate(item1):
            if len(result) <= j:
                result.append([])
            result[j].append(item2)
    return result


def apply_2dim(array, function):
    for item in array:
        function(item)
    return array


def parallelize(array_or_dict, func):
    class MyThread (threading.Thread):
        def __init__(self, item, key=None):
            threading.Thread.__init__(self)
            self.item = item
            self.key = key

        def run(self):
            if self.key:
                func(self.key, self.item)
            else:
                func(self.item)
    threads = []
    if isinstance(array_or_dict, list):
        for item in array_or_dict:
            t = MyThread(item)
            t.start()
            threads.append(t)
    elif isinstance(array_or_dict, dict):
        for key, item in array_or_dict.iteritems():
            t = MyThread(item, key)
            t.start()
            threads.append(t)
    else:
        raise Exception("Expected either array or dict")
    for t in threads:
        t.join()


def get_start_and_end(diff_secs, format="%m/%d/%Y %H:%M", escape=True):
    end_time = datetime.utcnow()
    start_time = (end_time + timedelta(seconds=-diff_secs))
    if isinstance(format, basestring):
        start_time = start_time.strftime(format)
        end_time = end_time.strftime(format)
        if escape:
            start_time = urllib.quote_plus(start_time)
            end_time = urllib.quote_plus(end_time)
    return [start_time, end_time]


def run_presto_query(presto_sql, hostname, port=8081):
    if presto_sql != "" and presto_sql is not None:
        cursor = pyhive.presto.connect(hostname, port).cursor()
        cursor.execute(presto_sql)
    else:
        raise Exception("Invalid Presto query: '%s'" % presto_sql)
    return cursor.fetchall()
