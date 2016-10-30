from datetime import datetime
import themis.constants
import themis.config


# based on http://stackoverflow.com/questions/1305532/convert-python-dict-to-object#answer-6573827
class Struct:
    '''The recursive class for building and representing objects with.'''
    def __init__(self, obj):
        for k, v in obj.iteritems():
            if isinstance(v, dict):
                setattr(self, k, Struct(v))
            else:
                setattr(self, k, v)

    def __getitem__(self, val):
        return self.__dict__[val]

    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for
            (k, v) in self.__dict__.iteritems()))


class NodesInfo:
    def __init__(self, nodes):
        self.running = nodes['running']
        self.active = nodes['active']
        self.count = CountStatsExpr(nodes['count'])
        self.average = AggregateStatsExpr(nodes['average'])
        self.total = AggregateStatsExpr(nodes['sum'])
        self.min = AggregateStatsExpr(nodes['min'])
        self.max = AggregateStatsExpr(nodes['max'])


class CountStatsExpr:
    def __init__(self, info):
        self.nodes = info.get('nodes')


class AggregateStatsExpr:
    def __init__(self, info):
        self.cpu = info.get('cpu')
        self.mem = info.get('mem')


class TimeBasedScaling:
    def __init__(self, info):
        self.enabled = info['enabled']
        self.minimum = TimeBasedMinimumNodes(info['minimum'])


class TimeBasedMinimumNodes:
    def __init__(self, info):
        self.nodes = info.get('nodes', [])


class ExprContext:
    def __init__(self, context):
        self.tasknodes = NodesInfo(context['tasknodes'])
        self.allnodes = NodesInfo(context['allnodes'])
        self.time_based = TimeBasedScaling(context['time_based'])


def execute_dsl_string(dsl_str, context, config=None):
    expr_context = Struct(context)

    for k, v in context.iteritems():
        exec('%s = expr_context.%s' % (k, k))

    now = datetime.utcnow()
    now_override = themis.config.get_value(themis.constants.KEY_NOW, config=config, default=None)
    if now_override:
        now = now_override

    return eval(dsl_str)
