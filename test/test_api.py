import requests
import json
import threading
import time
from constants import *
from themis.constants import *
from themis.util.common import FuncThread
from themis import api


TEST_API_PORT = 9876
TEST_API_ENDPOINT = 'http://localhost:%s' % TEST_API_PORT


def setup():
    thread = FuncThread(api.serve, TEST_API_PORT)
    thread.start()
    time.sleep(2)


def test_api_calls():
    response = requests.get('%s/healthcheck' % TEST_API_ENDPOINT)
    assert(response.status_code == 200)
    body = json.loads(response.text)
    assert(body['status'] == 'OK')

    response = requests.get('%s/swagger.json' % TEST_API_ENDPOINT)
    assert('Themis' in response.text)

    response = requests.get('%s/config/general' % TEST_API_ENDPOINT)
    configs = response.text
    assert('config' in json.loads(configs))

    response = requests.post('%s/config/general/' % TEST_API_ENDPOINT, data=configs)
    assert('config' in json.loads(response.text))

    request = '{"cluster_id": "test", "node_host": "test"}'
    response = requests.post('%s/emr/restart' % TEST_API_ENDPOINT, data=request)
    assert('Invalid cluster ID' in response.text)

    response = requests.get('%s/kinesis/streams' % TEST_API_ENDPOINT)
    assert('results' in json.loads(response.text))
