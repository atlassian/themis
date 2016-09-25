from themis.model.aws_model import *


class KinesisStream(Scalable, Monitorable):
    def __init__(self, id):
        super(KinesisStream, self).__init__(id)

    def fetch_data(self):
        print('Kinesis fetch_data')
        # TODO

    def needs_scaling(self, params=None):
        print('Kinesis needs_scaling')
        # TODO make decision here
        return True

    def perform_scaling(self, params=None):
        print('Kinesis perform_scaling')
        # TODO
