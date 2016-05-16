#!/usr/bin/env python

"""
Utility script to manage AWS pricing,
		decision support for manual cluster scaling, as well as
		cluster auto-scaling based on monitoring data.

Usage:
  scaling.py build
  scaling.py suggest (-c | --task-node-cpus) <task_node_cpus>
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
from util import math_util
from util import aws_pricing
from util.common import *

DEFAULT_PORT = 8000

TYPE_TO_CPUS = {
	'r3.2xlarge': 8,
	'r3.4xlarge': 16,
	'r3.8xlarge': 32
}

OD_TYPE = 'r3.4xlarge'

zones = ["us-east-1a"]
types = ["r3.2xlarge", "r3.4xlarge", "r3.8xlarge"]

def get_stats(values):
	return math_util.get_stats([float(v['SpotPrice']) for v in values])

def get_price_and_stats():
	result = {}
	for zone in zones:
		result[zone] = {}
		for type in types:
			result[zone][type] = {}
			price = aws_pricing.get_fixed_price(zone, type)
			values = aws_pricing.get_spot_history(zone, type)
			stats = get_stats(values)
			result[zone][type]['on_demand'] = price
			result[zone][type]['spot'] = stats
			result[zone][type]['spot_values'] = values
	return result

def fmt(num, after_comma=3):
	return ('{0:.%sf}' % after_comma).format(num)


def suggest(task_node_cpus):
	task_node_cpus = float(task_node_cpus)
	result = get_price_and_stats()
	log("Current AWS instance prices:")
	for zone in zones:
		for type in types:
			e = result[zone][type]
			spot = e['spot']
			log("  %s - %s -- on-demand: %s, spot (min/avg/max): %s/%s/%s" %
				(zone, type, e['on_demand'], spot['min'], spot['avg'], spot['max']))

	scores = {}

	#metrics = ['higher_spot', 'price_per_cpu', 'savings', 'downtime']
	metrics = ['savings', 'downtime']

	# initialize array
	for zone in zones:
		if not zone in scores:
			scores[zone] = {}
		for type in types:
			if not type in scores[zone]:
				scores[zone][type] = {}

	if 'higher_spot' in metrics:
		log("\nAnalyzing percentage of spot prices that are higher than on-demand prices (data from last 7 days):")
		max_higher = 0
		for zone in zones:
			for type in types:
				e = result[zone][type]
				higher = count_prices_higher_than(e['spot_values'], e['on_demand'])
				if higher > max_higher:
					max_higher = higher
				percentage = 100.0 * higher / len(e['spot_values'])
				scores[zone][type]['higher_spot'] = percentage
				log("  %s - %s -- %s of %s total time points (%s %%)" %
					(zone, type, higher, len(e['spot_values']), percentage))

	if 'price_per_cpu' in metrics:
		log("\nAnalyzing average 'price per vCPU' for spot instances (data from last 7 days):")
		max_avg_price = 0
		for zone in zones:
			for type in types:
				e = result[zone][type]
				avg_per_cpu = spot['avg'] / TYPE_TO_CPUS[type]
				if avg_per_cpu > max_avg_price:
					max_avg_price = avg_per_cpu
				spot = e['spot']
				scores[zone][type]['price_per_cpu'] = avg_per_cpu
				log("  %s - %s -- average price of %s USD per vCPU" %
					(zone, type, avg_per_cpu))

	if 'savings' in metrics:
		log("\nAnalyzing apprx. cost savings for spot instances compared to on-demand instances (data from last 7 days):")
		max_savings = 0
		savings_by_type = {}
		for zone in zones:
			for type in types:
				e = result[zone][type]
				savings = aws_pricing.get_cost_savings(e['on_demand'], e['spot_values'])
				if savings > max_savings:
					max_savings = savings
				savings_by_type[type] = savings
				scores[zone][type]['savings'] = savings
				log("  %s - %s -- %s USD cost savings" %
					(zone, type, savings))

	if 'downtime' in metrics:
		log("\nAnalyzing downtime for spot instances due to outbidding (data from last 7 days):")
		max_downtime = 0
		downtime_by_type = {}
		for zone in zones:
			for type in types:
				e = result[zone][type]
				downtime = aws_pricing.get_outbid_times(e['on_demand'], e['spot_values'])
				#save_spot_history_curve(e['on_demand'], e['spot_values'], type)
				if downtime > max_downtime:
					max_downtime = downtime
				downtime_by_type[type] = downtime
				scores[zone][type]['downtime'] = downtime
				log("  %s - %s -- %s hours outbid downtime" %
					(zone, type, downtime))

	log("\nWeighted scores:")
	score_array = []
	log("\t\t\t%s" % "".join(["\t\t%s" % m for m in metrics]))
	for zone in zones:
		for type in types:
			s = []
			w = []
			if 'higher_spot' in metrics:
				s.append(1 - (scores[zone][type]['higher_spot'] / max_higher))
				w.append(1)
			if 'price_per_cpu' in metrics:
				s.append(1 - (scores[zone][type]['price_per_cpu'] / max_avg_price))
				w.append(0.1)
			if 'savings' in metrics:
				s.append(scores[zone][type]['savings'] / max_savings)
				w.append(1)
			if 'downtime' in metrics:
				s.append(1 - (float(scores[zone][type]['downtime']) / max_downtime))
				w.append(1)

			score = sum([s[idx] * w[idx] for idx in range(0, len(s))])
			score_array.append(score)
			joined = ' \t+ '.join(["%s * %s" % (fmt(s[idx]), w[idx]) for idx in range(0, len(s))])
			log("  %s - %s -- score: \t%s \t= %s" %
				(zone, type, joined, fmt(score)))

	best_type = math_util.max_index(score_array)

	od_spot_ratio = 0.2
	od_cpu_per_instance = TYPE_TO_CPUS[OD_TYPE]
	od_cpus = math.ceil((task_node_cpus * od_spot_ratio) / od_cpu_per_instance) * od_cpu_per_instance
	od_instances = od_cpus / od_cpu_per_instance
	spot_type = types[best_type]
	spot_cpu_per_instance = TYPE_TO_CPUS[spot_type]
	spot_cpus = task_node_cpus - od_cpus
	spot_instances = round(spot_cpus / spot_cpu_per_instance)
	sum_cpus = od_instances * od_cpu_per_instance + spot_instances * spot_cpu_per_instance
	downtime = abs(1 * downtime_by_type[spot_type])
	total_savings = abs(spot_instances * savings_by_type[spot_type])

	print "\nSuggested cluster resource allocation:"
	print "  %s on-demand instances type '%s'" % (int(od_instances), OD_TYPE)
	print "  %s spot instances type '%s', bid price '%s'" % (int(spot_instances), spot_type, result[zones[0]][spot_type]['on_demand'])
	print "  = total of %s task node vCPUs (%s vCPUs requested)" % (int(sum_cpus), int(task_node_cpus))
	print("\nExpected results: apprx. %s hours expected downtime of spot instances, and %s USD cost savings per week (compared to on-demand instances)" %
		(downtime, fmt(total_savings)))


if __name__ == "__main__":
	args = docopt(__doc__)
	if args['suggest']:
		suggest(args['<task_node_cpus>'])
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
	if args['build']:
		subprocess.call("cd %s && npm install" % (os.path.dirname(os.path.realpath(__file__)) + "/scaling/web/"), shell=True)
