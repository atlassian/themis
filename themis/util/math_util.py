# common utility functions for mathematical operations


def vec_mult_items(vec1, vec2):
    result = []
    for idx, val in enumerate(vec1):
        result.append(vec1[idx] * vec2[idx])
    return result


def vec_sum(vec1, vec2):
    result = []
    for idx, val in enumerate(vec1):
        result.append(vec1[idx] + vec2[idx])
    return result


def max_index(list):
    max_idx = 0
    for idx, val in enumerate(list):
        if val > list[max_idx]:
            max_idx = idx
    return max_idx


def get_stats(values):
    sum = 0
    min = float("inf")
    max = 0
    for num in values:
        sum += num
        if num > max:
            max = num
        if num < min:
            min = num
    result = {}
    result['num'] = len(values)
    result['sum'] = sum
    result['min'] = min
    result['max'] = max
    result['avg'] = sum / len(values) if values else float('NaN')
    return result
