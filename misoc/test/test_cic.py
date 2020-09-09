import numpy as np
import unittest
from migen import *

from misoc.cores import cic

def feed(endpoint, x, rate):
    n, d = rate
    t = 0
    for i, xi in enumerate(x):
        while t*n < i*d:
            yield
            t += 1
        yield endpoint.data.eq(int(xi))
        yield endpoint.stb.eq(1)
        yield
        t += 1
        while not (yield endpoint.ack):
            yield
        yield endpoint.stb.eq(0)


@passive
def retrieve(endpoint, o):
    yield
    while True:
        yield endpoint.ack.eq(1)
        yield
        while not (yield endpoint.stb):
            yield
        o.append(((yield endpoint.data0), (yield endpoint.data1)))
        yield endpoint.ack.eq(0)


def cic_up(x, n, r):
    for _ in range(n):
        x = np.diff(np.r_[0, x])
    x = np.c_[x, np.zeros((len(x), r - 1), np.int64)].ravel()
    for _ in range(n):
        x = np.cumsum(x)
    return x


class TestCIC(unittest.TestCase):
    def setUp(self):
        self.dut = cic.SuperCIC(n=4, r=5, width=4)

    def test_init(self):
        self.assertEqual(len(self.dut.input.data), 4)
        self.assertEqual(len(self.dut.output.data0), 11)
        self.assertEqual(len(self.dut.output.data1), 11)

    def test_seq(self):
        x = [1, 7, -8, 7, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        y = []
        run_simulation(self.dut, [feed(self.dut.input, x, (2, 5)),
                                  retrieve(self.dut.output, y)])
        y = np.ravel(y)[35:]
        y0 = cic_up(x, n=4, r=5)[:len(y)]
        np.testing.assert_equal(y, y0)
