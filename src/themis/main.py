#!/usr/bin/env python

"""
Main script for cluster auto-scaling based on monitoring data.

Usage:
  main.py build
  main.py server [ --port=<port> ] [ --log=<log_file> ]
  main.py loop [ --log=<log_file> ]
  main.py server_and_loop [ --port=<port> ] [ --log=<log_file> ]
  main.py (-h | --help)

Options:
  -h --help     		Show this screen.
  --port=<port>  		Port the server should listen on.
  --log=<log_file>     	Log file path.
"""

import subprocess
from docopt import docopt
import math
import logging
from themis import config
from themis.util.common import *

DEFAULT_PORT = 8000

if __name__ == "__main__":
	args = docopt(__doc__)
	port = args['--port'] or DEFAULT_PORT
	log_file = args['--log'] or ''

	# set up logging
	setup_logging(log_file)

	if args['server_and_loop']:
		config.init_clusters_file()
		def run(cmd):
			subprocess.call(cmd, shell=True)
		cmd = os.path.realpath(__file__) + " loop --log=%s" % (log_file)
		t1 = threading.Thread(target = run, args = (cmd,))
		t1.start()
		cmd = os.path.realpath(__file__) + " server --port=%s --log=%s" % (port, log_file)
		t2 = threading.Thread(target = run, args = (cmd,))
		t2.start()
		try:
			t2.join()
		except KeyboardInterrupt, e:
			pass
	else:
		if args['server']:
			from scaling import server
			server.serve(port)
		if args['loop']:
			from scaling import server
			try:
				server.loop()
			except KeyboardInterrupt, e:
				pass

