import os
from themis.util import aws_common, common

AWS_API_PORT = 9896
GANGLIA_PORT = 9897
LOCALHOST = '127.0.0.1'
BIND_HOST = '0.0.0.0'
DEFAULT_REGION = 'us-east-1'

# set test values for boto3 credentials
os.environ['AWS_DEFAULT_REGION'] = DEFAULT_REGION
os.environ['AWS_ACCESS_KEY_ID'] = 'test_access_key'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'test_secret_key'

try:
    tmp = os.environ.AWS_ENDPOINT_URL
except AttributeError, e:
    import mock.aws_api
    os.environ.AWS_ENDPOINT_URL = 'http://%s:%s/aws' % (LOCALHOST, AWS_API_PORT)
    common.setup_logging()
    mock.aws_api.init_aws_cli()
    aws_common.init_aws_cli()
