import threading
import subprocess
import os
import re
import time
import urllib
import glob
import json
import math
import pyhive.presto
from datetime import datetime, timedelta
from collections import namedtuple

def log(s):
	# TODO add proper logging
	print(s)

CACHE_CLEAN_TIMEOUT = 60 * 5
CACHE_MAX_AGE = 60 * 60
CACHE_FILE_PATTERN = '/tmp/cache.*.json'

# connect timeout for curl commands
CURL_CONNECT_TIMEOUT = 3

# cache query results
QUERY_CACHE_TIMEOUT = 60
GANGLIA_CACHE_TIMEOUT = 60
STATIC_INFO_CACHE_TIMEOUT = 60 * 30

last_cache_clean_time = 0

mutex_clean = threading.Semaphore(1)

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
	save_file(json.dumps(content))

def is_composite(o):
	return isinstance(o, list) or isinstance(o, dict)

def is_float(f):
	return isinstance(f, float) and not math.isnan(f)

def remove_lines_from_string(s,regex):
	return '\n'.join([line for line in s.split('\n') if not re.match(regex, line)])

def remove_NaN(obj):
	if isinstance(obj, list):
		for i in range (0,len(obj)):
			if isinstance(obj[i], float) and math.isnan(obj[i]):
				obj[i] = "NaN"
			if is_composite(obj[i]):
				remove_NaN(obj[i])
	elif isinstance(obj, dict):
		for key,val in obj.iteritems():
			if isinstance(val, float) and math.isnan(val):
				obj[key] = "NaN"
			if is_composite(obj[key]):
				remove_NaN(obj[key])

def inject_aws_endpoint(cmd):
	try:
		if not os.environ.AWS_ENDPOINT_URL:
			return cmd
		regex = r'^aws ([^\s]+) ([^\s]+)(.*)$'
		if re.match(regex, cmd):
			cmd = re.sub(regex, r'aws --endpoint-url="%s/\1/\2" \1 \2\3' % os.environ.AWS_ENDPOINT_URL, cmd)
	except AttributeError, e:
		pass
	print(cmd)
	return cmd

def run(cmd, cache_duration_secs=0, print_error=False):
	def do_run(cmd):
		try:
			return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
		except subprocess.CalledProcessError, e:
			if print_error:
				print("ERROR: %s" % e.output)
			raise e
	cmd = inject_aws_endpoint(cmd)
	if cache_duration_secs <= 0:
		return do_run(cmd)
	hash = md5(cmd)
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
	result = do_run(cmd)
	f = open(cache_file, 'w+')
	f.write(result)
	f.close()
	clean_cache()
	return result

def run_ssh(cmd, host, user=None, keys=None, via_hosts=[], cache_duration_secs=0):
	if not keys:
		keys = ['~/.ssh/atl-ai-etl-prod.pem', '~/.ssh/atl-ai-etl-dev.pem', '~/.ssh/ai-etl.pem']

	user = '%s@' % user if user else ''

	agent_forward = ''
	forward_addendum = ''
	hostcheck_addendum = '-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'

	if len(via_hosts) > 0:
		agent_forward = '-o ForwardAgent=yes'
		for via_host in list(reversed(via_hosts)):
			forward_addendum = ('ssh %s %s%s ' % (hostcheck_addendum,user,via_host)) + forward_addendum

	ssh_cmd_tmpl = 'ssh ' + hostcheck_addendum + ' ' + agent_forward + ' -i %s %s%s "' + forward_addendum + '%s"'

	for key in keys:
		ssh_cmd = ssh_cmd_tmpl % (key, user, host, cmd)
		#print(ssh_cmd)

		if len(via_hosts) > 0:
			run('ssh-add %s 2>&1 > /dev/null' % key)

		try:
			out = run(ssh_cmd, cache_duration_secs)
			return out
		except subprocess.CalledProcessError, e:
			# TODO find a more elegant solution for this.
			if 'Permission denied (publickey)' not in e.output:
				raise e

	raise Exception('Cannot run SSH command with any of the provided ssh keys: %s%s %s %s' % (user,host,cmd,keys))

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

def get_start_and_end(diff_secs, format="%m/%d/%Y %H:%M"):
	d = datetime.utcnow()
	start_time = (d + timedelta(seconds=-diff_secs))
	start_time = start_time.strftime(format)
	end_time = d.strftime(format)
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
