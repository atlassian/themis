import re
import os
import json
from datetime import date, timedelta, datetime
import math
import time
import subprocess
from scipy import integrate, interpolate
from themis.util.common import *
from themis.util.exceptions import *

LOCATION_NAMES = {
    'us-east-1': 'US East (N. Virginia)'
}

LOG = get_logger(__name__)


def get_short_zone(zone):
    zone = re.sub(r'-([1-9])[a-z]$', r'-\1', zone)
    return zone


def get_spot_history(zone, type):
    d = date.today()
    format = "%Y-%m-%dT00:00:00"
    end_time = d.strftime(format)
    start_time = (d + timedelta(days=-7)).strftime(format)
    date_format = "%Y-%m-%dT00:00:00"
    end_date = d.strftime(date_format)
    start_date = (d + timedelta(days=-7)).strftime(date_format)
    file = "/tmp/aws_spot_%s_%s_%s_%s.json" % (zone, type, start_date, end_date)

    result = None
    if os.path.isfile(file):
        result = open(file).read()
        result = json.loads(result)
    else:
        cmd = ("aws ec2 describe-spot-price-history --start-time %s --end-time %s --availability-zone %s " +
            "--instance-types %s --max-items 15000") % (start_time, end_time, zone, type)
        LOG.info('Loading AWS spot prices for zone "%s" and type "%s"' % (zone, type))
        result = run(cmd)
        open(file, 'w+').write(result)
        result = json.loads(result)
    values = result['SpotPriceHistory']
    return values


def load_fixed_prices(zone):
    zone = get_short_zone(zone)
    url = "https://pricing.%s.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/index.json" % zone
    file = "/tmp/aws_fixed_%s.json" % zone
    result = None
    if os.path.isfile(file):
        result = open(file).read()
        try:
            result = json.loads(result)
        except Exception, e:
            # download failed, delete file
            os.remove(file)
            result = None

    if not result:
        LOG.info("Downloading latest pricing information from AWS")
        try:
            cmd = "curl %s > %s" % (url, file)
            run(cmd)
        except Exception, e:
            raise ConnectivityException('Unable to get pricing information.')
        result = open(file).read()
        result = json.loads(result)
    return result


def get_fixed_price(zone, type, os='Linux', tenancy='Shared'):
    zone = get_short_zone(zone)
    doc = load_fixed_prices(zone)
    result = None
    for key, product in doc['products'].iteritems():
        attrs = product['attributes']
        if 'instanceType' in attrs:
            if type == attrs['instanceType']:
                loc = attrs['location']
                if tenancy == attrs['tenancy'] and loc == LOCATION_NAMES[zone]:
                    if os and os == attrs['operatingSystem']:
                        prices = doc['terms']['OnDemand'][key]
                        if len(prices) > 1:
                            raise Exception("Multiple price entries found for %s" % key)
                        price_dim = prices.values()[0]['priceDimensions']
                        if len(price_dim) > 1:
                            raise Exception("Multiple price dimensions found for %s" % key)
                        price = float(price_dim.values()[0]['pricePerUnit']['USD'])
                        if result:
                            LOG.info('WARNING: multiple prices detected %s %s' % (price, attrs['operatingSystem']))
                        else:
                            result = price
    return result


def filter_prices_higher_than(list, price):
    result = []
    for item in list:
        if float(item['SpotPrice']) > price:
            result.append(item)
    return result


def count_prices_higher_than(list, price):
    result = filter_prices_higher_than(list, price)
    return len(result)


def get_spot_history_curve(spot_history):
    x = []
    y = []
    format = "%Y-%m-%dT%H:%M:%S.%fZ"
    prev_t = 0
    for item in spot_history:
        t = time.mktime(datetime.strptime(item['Timestamp'], format).timetuple())
        delta = abs(t - prev_t)
        prev_t = t
        if delta > 0:
            x.append(t)
            y.append(float(item['SpotPrice']))
    return {"x": x, "y": y}


def save_spot_history_curve(od_price, spot_history, type):
    file = '/tmp/aws_spot_history%s.csv' % type
    f = open(file, 'w+')
    curve = get_spot_history_curve(spot_history)
    for idx, item in enumerate(curve['x']):
        line = "%s, %s, %s\n" % (curve['x'][idx], curve['y'][idx], od_price)
        f.write(line)


def get_outbid_times(od_price, spot_history):
    curve = get_spot_history_curve(spot_history)
    func = interpolate.interp1d(curve['x'], curve['y'])
    start_time = curve['x'][-1]
    end_time = curve['x'][0]
    outbid_hours = 0
    t = start_time
    while t <= end_time:
        # check every 2 minutes for outbidding
        for t1 in range(0, 60 * 60, 2 * 60):
            if (t + t1) > end_time:
                continue
            estimated_spot_price = func(t + t1)
            if estimated_spot_price > od_price:
                outbid_hours += 1
                break
        t += 60 * 60  # add one hour in seconds
    return outbid_hours


def get_cost_savings(od_price, spot_history):
    curve = get_spot_history_curve(spot_history)
    for idx, item in enumerate(curve['y']):
        curve['y'][idx] = max(od_price - curve['y'][idx], 0)
    integrated = integrate.simps(curve['y'], curve['x'])
    # convert unit from seconds to hours
    integrated /= 60 * 60
    return abs(integrated)


def get_cluster_savings(info, baseline_nodes, zone='us-east-1'):
    result = {}
    instance_start_times = {}
    instance_end_times = {}
    instance_types = {}
    all_nodes = set()
    instance_type_prices = {}
    start_time = float("inf")
    end_time = 0
    total_costs = 0
    total_hours = 0
    baseline_instance_type = None
    # TODO: don't hardcode!!
    default_instance_type = "r3.2xlarge"
    for point in info:
        timestamp = float(point['timestamp'])
        if timestamp < start_time:
            start_time = timestamp
        if timestamp > end_time:
            end_time = timestamp
        state = point['state']
        tasknodes = state['tasknodes']
        allnodes = state['allnodes']
        groups = state['groups'] if 'groups' in state else {}
        for gid, details in groups.iteritems():
            if not isinstance(details, dict):
                continue
            nodes = details['instances']
            for node_obj in nodes:
                node = node_obj['iid']
                all_nodes.add(node)
                # TODO: don't hardcode!!
                instance_types[node] = default_instance_type
                if instance_types[node] not in instance_type_prices:
                    instance_type_prices[instance_types[node]] = get_fixed_price(zone, instance_types[node])
                if not baseline_instance_type:
                    baseline_instance_type = instance_types[node]
                if baseline_instance_type != instance_types[node]:
                    LOG.warn("Found different node instance types. Using type '%s' as baseline" %
                        baseline_instance_type)
                if node not in instance_end_times or instance_end_times[node] < timestamp:
                    instance_end_times[node] = timestamp
                if node not in instance_start_times or instance_start_times[node] > timestamp:
                    instance_start_times[node] = timestamp

    result['instances'] = []

    for node in all_nodes:
        end = instance_end_times[node] / 1000.0
        start = instance_start_times[node] / 1000.0
        duration = end - start
        hours = duration / 60.0 / 60.0
        hours = math.ceil(hours)
        total_hours += hours
        inst_costs = hours * instance_type_prices[instance_types[node]]
        total_costs += inst_costs
        result['instances'].append({
            'iid': node,
            'start': start,
            'end': end,
            'hours': hours,
            'costs': inst_costs
        })

    # convert timestamps to seconds
    start_time = start_time / 1000.0
    end_time = end_time / 1000.0
    duration_hours = math.ceil((end_time - start_time) / 60.0 / 60.0)
    # compute baseline costs
    baseline_costs = baseline_nodes * get_fixed_price(zone, default_instance_type) * duration_hours

    # prepare result
    result['start_time'] = start_time
    result['end_time'] = end_time
    result['hours'] = total_hours
    result['costs'] = total_costs
    result['costs_baseline'] = baseline_costs
    result['saved'] = result['costs_baseline'] - result['costs']
    result['duration'] = end_time - start_time
    result['saved_per_second'] = (result['saved'] / result['duration']) if result['duration'] > 0 else 0
    return result
