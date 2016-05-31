
class NodesInfo:
    def __init__(self, nodes):
        self.running = nodes['running']
        self.active = nodes['active']
        self.count = CountStatsExpr(nodes['count'])
        self.average = AverageStatsExpr(nodes['average'])

class CountStatsExpr:
    def __init__(self, info):
        if 'nodes' in info:
            self.nodes = info['nodes']

class AverageStatsExpr:
    def __init__(self, info):
        if 'cpu' in info:
            self.cpu = info['cpu']
        if 'mem' in info:
            self.mem = info['mem']

class TimeBasedScaling:
    def __init__(self, info):
        self.enabled = info['enabled']
        self.minimum = TimeBasedMinimumNodes(info['minimum'])

class TimeBasedMinimumNodes:
    def __init__(self, info):
        self.nodes = info['nodes']

class ExprContext:
    def __init__(self, context):
        self.tasknodes = NodesInfo(context['tasknodes'])
        self.allnodes = NodesInfo(context['allnodes'])
        self.time_based = TimeBasedScaling(context['time_based'])
