import os

AWS_API_PORT = 9896
GANGLIA_PORT = 9897
LOCALHOST = '127.0.0.1'
BIND_HOST = '0.0.0.0'


try:
    tmp = os.environ.AWS_ENDPOINT_URL
except AttributeError, e:
    import mock.aws_api
    os.environ.AWS_ENDPOINT_URL = 'http://%s:%s/aws' % (LOCALHOST, AWS_API_PORT)
    mock.aws_api.init_aws_cli()
