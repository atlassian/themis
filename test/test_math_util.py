from themis.util import math_util


def test_utils():

    values = [1, 2, 3, 1, 4]
    stats = math_util.get_stats(values)
    assert stats['sum'] == 11
    assert stats['min'] == 1
    assert stats['max'] == 4

    vec1 = [1, 2, 3, 1, 4]
    vec2 = [1, 2, 0, 3, -1]
    mult = math_util.vec_mult_items(vec1, vec2)
    assert mult == [1, 4, 0, 3, -4]
    vec_sum = math_util.vec_sum(vec1, vec2)
    assert vec_sum == [2, 4, 3, 4, 3]

    values = [1, 2, 3, 1, 4, -5]
    idx = math_util.max_index(values)
    assert idx == 4
