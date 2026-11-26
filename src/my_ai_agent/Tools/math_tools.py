"""Common numerical operations exposed by name, without evaluating source code."""

from fractions import Fraction
import json
import math
import operator
import statistics
from typing import Any

from langchain_core.tools import tool


def _factorial(n: int):
    if not isinstance(n, int) or not 0 <= n <= 1500:
        raise ValueError("factorial 的 n 须为 0 到 1500 的整数。")
    return math.factorial(n)


def _permutation(n: int, k: int | None = None):
    if not isinstance(n, int) or not 0 <= n <= 1500:
        raise ValueError("perm 的 n 须为 0 到 1500 的整数。")
    return math.perm(n, k)


def _combination(n: int, k: int):
    if not isinstance(n, int) or not 0 <= n <= 10000:
        raise ValueError("comb 的 n 须为 0 到 10000 的整数。")
    return math.comb(n, k)


def _pow(base, exponent, modulus=None):
    if modulus is not None:
        return pow(base, exponent, modulus)
    if isinstance(base, int) and isinstance(exponent, int) and exponent > 0:
        if abs(base) > 1 and base.bit_length() * exponent > 13000:
            raise ValueError("整数幂结果过大。")
    return pow(base, exponent)


def _shift_left(n, bits):
    if not isinstance(bits, int) or not 0 <= bits <= 13000:
        raise ValueError("左移位数须为 0 到 13000 的整数。")
    return n << bits


def _fraction(numerator, denominator=None):
    value = Fraction(numerator) if denominator is None else Fraction(numerator, denominator)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _mod_inverse(value, modulus):
    return pow(value, -1, modulus)


def _normal_cdf(value, mean=0, stdev=1):
    return statistics.NormalDist(mean, stdev).cdf(value)


def _normal_quantile(probability, mean=0, stdev=1):
    return statistics.NormalDist(mean, stdev).inv_cdf(probability)


def _cross(left, right):
    x, y, z = left
    a, b, c = right
    return [y * c - z * b, z * a - x * c, x * b - y * a]


def _prime_factors(n: int):
    if not isinstance(n, int) or not 1 <= n <= 10**12:
        raise ValueError("因数分解支持 1 到 10^12 之间的整数。")
    factors = []
    divisor = 2
    while divisor * divisor <= n:
        while n % divisor == 0:
            factors.append(divisor)
            n //= divisor
        divisor = 3 if divisor == 2 else divisor + 2
    if n > 1:
        factors.append(n)
    return factors


def _is_prime(n: int):
    if not isinstance(n, int):
        raise ValueError("is_prime 需要整数。")
    return n >= 2 and _prime_factors(n) == [n]


def _clamp(value, minimum, maximum):
    if minimum > maximum:
        raise ValueError("minimum 不能大于 maximum。")
    return min(max(value, minimum), maximum)


def _matrix_shape(rows):
    if not rows or not rows[0]:
        raise ValueError("矩阵不能为空。")
    height, width = len(rows), len(rows[0])
    if height > 128 or width > 128 or any(len(row) != width for row in rows):
        raise ValueError("矩阵须为至多 128 × 128 的矩形。")
    return height, width


def _transpose(rows):
    _matrix_shape(rows)
    return list(zip(*rows))


def _matrix_multiply(left, right):
    _, inner = _matrix_shape(left)
    if inner != len(right):
        raise ValueError("左矩阵列数须等于右矩阵行数。")
    columns = _transpose(right)
    return [[math.sumprod(row, column) for column in columns] for row in left]


def _row_echelon(rows, vector=None):
    height, width = _matrix_shape(rows)
    if height != width or height > 32:
        raise ValueError("行列式和线性方程求解需要至多 32 × 32 的方阵。")
    if vector is not None and len(vector) != height:
        raise ValueError("右端向量长度须等于矩阵行数。")
    matrix = [list(map(Fraction, row)) for row in rows]
    if vector is not None:
        for index, value in enumerate(vector):
            matrix[index].append(Fraction(value))
    determinant = Fraction(1)
    for column in range(width):
        pivot = max(range(column, height), key=lambda index: abs(matrix[index][column]))
        if not matrix[pivot][column]:
            return 0, matrix
        if pivot != column:
            matrix[pivot], matrix[column] = matrix[column], matrix[pivot]
            determinant = -determinant
        determinant *= matrix[column][column]
        for index in range(column + 1, height):
            if matrix[index][column] == 0:
                continue
            scale = matrix[index][column] / matrix[column][column]
            for j in range(column, len(matrix[index])):
                matrix[index][j] -= scale * matrix[column][j]
    return determinant, matrix


def _rational_value(value):
    return int(value) if isinstance(value, int) or value.denominator == 1 else float(value)


def _determinant(rows):
    determinant, _ = _row_echelon(rows)
    return _rational_value(determinant)


def _solve_linear(rows, vector):
    determinant, matrix = _row_echelon(rows, vector)
    if determinant == 0:
        raise ValueError("矩阵奇异，方程组没有唯一解。")
    size = len(matrix)
    solution = [Fraction(0)] * size
    for i in reversed(range(size)):
        row = matrix[i]
        solution[i] = (row[-1] - sum(row[j] * solution[j] for j in range(i + 1, size))) / row[i]
    return [_rational_value(value) for value in solution]


OPERATIONS = {
    "算术": {
        "add": operator.add, "subtract": operator.sub, "multiply": operator.mul,
        "divide": operator.truediv, "floor_divide": operator.floordiv,
        "mod": operator.mod, "divmod": divmod, "pow": _pow, "abs": abs, "round": round,
        "min": min, "max": max, "sum": sum, "fsum": math.fsum, "prod": math.prod, "clamp": _clamp,
        "fraction": _fraction,
    },
    "实数函数": {
        name: getattr(math, name)
        for name in (
            "floor", "ceil", "trunc", "sqrt", "cbrt", "exp", "expm1", "log", "log1p", "log2",
            "log10", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh",
            "tanh", "asinh", "acosh", "atanh", "degrees", "radians", "hypot", "dist",
            "copysign", "fmod", "remainder", "isclose", "frexp", "ldexp", "fma", "erf",
            "erfc", "gamma", "lgamma",
        )
    },
    "数论与组合": {
        "gcd": math.gcd, "lcm": math.lcm, "isqrt": math.isqrt, "factorial": _factorial,
        "comb": _combination, "perm": _permutation, "is_prime": _is_prime,
        "prime_factors": _prime_factors, "mod_inverse": _mod_inverse,
    },
    "概率": {"normal_cdf": _normal_cdf, "normal_quantile": _normal_quantile},
    "统计": {
        name: getattr(statistics, name)
        for name in (
            "mean", "fmean", "median", "median_low", "median_high", "mode", "multimode",
            "pstdev", "stdev", "pvariance", "variance", "quantiles", "geometric_mean",
            "harmonic_mean", "covariance", "correlation", "linear_regression",
        )
    },
    "位运算和进制": {
        "bit_and": operator.and_, "bit_or": operator.or_, "bit_xor": operator.xor,
        "bit_not": operator.invert, "shift_left": _shift_left, "shift_right": operator.rshift,
        "bit_count": int.bit_count, "bit_length": int.bit_length, "parse_int": int,
        "bin": bin, "oct": oct, "hex": hex,
    },
    "线性代数": {
        "dot": math.sumprod, "cross": _cross, "transpose": _transpose, "matrix_multiply": _matrix_multiply,
        "determinant": _determinant, "solve_linear": _solve_linear,
    },
}
FUNCTIONS = {name: function for operations in OPERATIONS.values() for name, function in operations.items()}


@tool
def math_compute(
    operation: str, arguments: list[Any] | None = None, keyword_arguments: dict[str, Any] | None = None,
) -> dict:
    """执行常用数学及编程计算。operation="list" 列出所有可用运算和常量。

    arguments 按 Python 函数顺序传入位置参数，keyword_arguments 传关键字参数。
    例如 gcd arguments=[36, 60]、mean arguments=[[1, 2, 3]]、
    pow arguments=[2, 20, 17]（模幂）、quantiles arguments=[[1,2,3,4]] keyword_arguments={"n":4}。
    三角函数使用弧度；需要自定义算法或大批量计算时使用 execute_python。
    """
    if operation == "list":
        return {
            "ok": True, "operations": {group: list(operations) for group, operations in OPERATIONS.items()},
            "constants": {"pi": math.pi, "e": math.e, "tau": math.tau},
        }
    if operation not in FUNCTIONS:
        return {"ok": False, "error": "未知运算。请用 operation=list 查看可用运算。"}
    try:
        args = arguments or []
        kwargs = keyword_arguments or {}
        if operation == "quantiles" and kwargs.get("n", 4) > 1000:
            raise ValueError("quantiles 的 n 最大为 1000。")
        result = FUNCTIONS[operation](*args, **kwargs)
        if operation == "linear_regression":
            result = result._asdict()
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(encoded) > 16_000:
            raise ValueError("结果超过 16000 字符，请缩小计算范围或使用 execute_python。")
        return {"ok": True, "result": json.loads(encoded)}
    except (ArithmeticError, RecursionError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
