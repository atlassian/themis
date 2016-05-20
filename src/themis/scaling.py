#!/usr/bin/env python

"""
Main script for cluster auto-scaling based on monitoring data.

Usage:
  scaling.py build
  scaling.py server [ (-p | --port) <port> ]
  scaling.py loop
  scaling.py server_and_loop [ (-p | --port) <port> ]
  scaling.py (-h | --help)

Options:
  -h --help     Show this screen.

"""

import subprocess
from docopt import docopt
import math
from themis.util import math_util
from themis.util import aws_pricing
from themis.util.common import *

DEFAULT_PORT = 8000

TYPE_TO_CPUS = {
	'r3.2xlarge': 8,
	'r3.4xlarge': 16,
	'r3.8xlarge': 32
}

OD_TYPE = 'r3.4xlarge'

zones = ["us-east-1a"]
types = ["r3.2xlarge", "r3.4xlarge", "r3.8xlarge"]

if __name__ == "__main__":
	args = docopt(__doc__)
	if args['server_and_loop']:
		def run(cmd):
			subprocess.call(cmd, shell=True)
		port = args['<port>'] or DEFAULT_PORT
		cmd = os.path.realpath(__file__) + " loop"
		t1 = threading.Thread(target = run, args = (cmd,))
		t1.start()
		cmd = os.path.realpath(__file__) + " server -p %s" % port
		t2 = threading.Thread(target = run, args = (cmd,))
		t2.start()
		try:
			t2.join()
		except KeyboardInterrupt, e:
			pass
	if args['server']:
		from scaling import server
		port = args['<port>'] or DEFAULT_PORT
		server.serve(port)
	if args['loop']:
		from scaling import server
		try:
			server.loop()
		except KeyboardInterrupt, e:
			pass

