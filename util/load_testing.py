import common
import time

errors = []

def query(cluster_ip, query):
	try:
		result = common.run_presto_query(query, cluster_ip)
		print(result)
		return result
	except Exception, e:
		errors.append(e)
		return False

def run_queries(cluster_ip, num=20):
	def run_it(sql):
		query(cluster_ip, sql)

	queries = [
		"SELECT COUNT(*) FROM raw_hams.persistedorder o INNER JOIN raw_hams.persistedorderitem i ON i.order_id=o.id WHERE i.description LIKE '%a%'"
	]
	for i in range(0,num):
		queries.append(queries[0])
	common.parallelize(queries, run_it)

def run_test(cluster_ip, iterations=10, num_queries=20, iteration_delay=20):
	total_errors = 0
	for i in range(0,iterations):
		run_queries(cluster_ip, num_queries)
		total_errors += len(errors)
		print "%s query errors in this iteration" % len(errors)
		time.sleep(iteration_delay)
	print "Done. Total query errors: %s" % len(errors)

if __name__ == '__main__':
	host = '52.90.231.115' # presto dev cluster public IP
	run_test(host, iterations=15, num_queries=5, iteration_delay=1)
