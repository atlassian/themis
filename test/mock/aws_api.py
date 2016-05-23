from flask import Flask, request, make_response
from flask_swagger import swagger
import json
import re
import os
import threading
from themis.util import common

def serve(port):
	class AwsApiApp(threading.Thread):
		def __init__(self):
			threading.Thread.__init__(self)
			self.cpu = None
			self.mem = None
			self.app = Flask('testapp')
		def run(self):
			@self.app.route('/<path:path>', methods=['GET', 'PUT', 'POST', 'DELETE'])
			def handle(path):
				result = mock_aws_api(request.method, path, request)
				return result
			self.app.run(port=int(port), host='0.0.0.0')
	app = AwsApiApp()
	app.daemon = True
	app.start()
	return app

def init_aws_cli():
	home = os.path.expanduser("~")
	folder = '%s/.aws' % home
	if not os.path.exists(folder):
		os.makedirs(folder)
	file_config = '%s/.aws/config' % home
	if not os.path.isfile(file_config):
		common.save_file(file_config, "[default]\nregion = us-east-1")
	file_creds = '%s/.aws/credentials' % home
	if not os.path.isfile(file_creds):
		common.save_file(file_creds,  "[default]\naws_access_key_id = testAccessKeyId\naws_secret_access_key = testSecretKey")

def mock_aws_api(method, path, req):
	result = {}
	if re.match(r'.*/emr/list-clusters', path):
		result = {
			"Clusters": [
				{
					"Id": "testClusterID1", 
					"Name": "testCluster1",
					"NormalizedInstanceHours": 1, 
					"Status": {
						"Timeline": {
							"ReadyDateTime": 1463909324.869, 
							"CreationDateTime": 1463908895.082
						}, 
						"State": "WAITING", 
						"StateChangeReason": {
							"Message": "Cluster ready to run steps."
						}
					}
				}
			]
		}
	print(result)
	return make_response(json.dumps(result))
