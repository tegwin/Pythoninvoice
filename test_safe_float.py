"""NaN or inf in a money field must not reach the arithmetic."""
from app_web import safe_float


def test_rejects_non_finite():
    for bad in ['nan', 'NaN', 'inf', '-inf', 'Infinity', '-Infinity']:
        assert safe_float(bad) == 0.0, f"{bad!r} got through"


def test_rejects_garbage():
    for bad in ['abc', '1,5', None, '', '12abc']:
        assert safe_float(bad) == 0.0, f"{bad!r} got through"


def test_passes_real_numbers():
    assert safe_float('20') == 20.0
    assert safe_float('19.5') == 19.5
    assert safe_float('-3.25') == -3.25
    assert safe_float(0) == 0.0


def test_honours_default():
    assert safe_float('nan', None) is None
    assert safe_float('', 7) == 7


if __name__ == '__main__':
    for fn in [test_rejects_non_finite, test_rejects_garbage,
               test_passes_real_numbers, test_honours_default]:
        fn()
    print('safe_float checks passed')
