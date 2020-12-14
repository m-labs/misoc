import numpy as np
import unittest
import random
from migen import *

from misoc.cores import fir


class TestDSP(unittest.TestCase):
    def setUp(self):
        self.dut = fir.DSP()

    def test_init(self):
        self.assertEqual(len(self.dut.a), 24)
        self.assertEqual(len(self.dut.b), 18)
        self.assertEqual(len(self.dut.c), 48)
        self.assertEqual(len(self.dut.d), 24)
        self.assertEqual(len(self.dut.p), 48)
        self.assertEqual(len(self.dut.m), 48)

    def test_seq(self):
        def gen():
            a, b, c, d = 0x123, -0x456, 0x789, 0x357
            yield self.dut.a.eq(a)
            yield self.dut.d.eq(d)
            yield self.dut.presub.eq(1)
            yield
            self.assertEqual((yield self.dut.ar), a)
            self.assertEqual((yield self.dut.dr), d)
            yield self.dut.b.eq(b)
            yield
            self.assertEqual((yield self.dut.br), b)
            self.assertEqual((yield self.dut.adr), a - d)
            yield self.dut.c.eq(c)
            yield
            self.assertEqual((yield self.dut.cr), c)
            self.assertEqual((yield self.dut.mr), (a - d)*b)
            yield
            self.assertEqual((yield self.dut.pr), (a - d)*b + c)
        run_simulation(self.dut, gen())


class TestSRStorage(unittest.TestCase):
    def setUp(self):
        self.dut = fir.SRStorage(3, 8)

    def test_init(self):
        self.assertEqual(len(self.dut.load.data), 8)
        self.assertEqual(len(self.dut.out.data), 8)

    def load(self, d):
        yield self.dut.load.eop.eq(1)
        for i in d:
            for _ in range(random.randint(0, 15)):
                yield
            yield self.dut.load.data.eq(i)
            yield self.dut.load.stb.eq(1)
            yield
            while not (yield self.dut.load.ack):
                yield
            yield self.dut.load.stb.eq(0)

    @passive
    def retrieve(self, o):
        o.append([])
        while True:
            for _ in range(random.randint(0, 4)):
                yield
            yield self.dut.out.ack.eq(1)
            yield
            while not (yield self.dut.out.stb):
                yield
            o[-1].append((yield self.dut.out.data))
            if (yield self.dut.out.eop):
                o.append([])
            yield self.dut.out.ack.eq(0)

    def test_seq(self):
        o = []
        random.seed(42)
        run_simulation(self.dut, [self.load(range(10)), self.retrieve(o)])
        for i, oi in enumerate(o[2:-1]):
            with self.subTest(i=i):
                if not oi:
                    continue
                self.assertEqual(oi, list(range(i, i + 3)))


def feed(endpoint, x, maxwait=20):
    for i in x:
        for _ in range(random.randint(0, maxwait)):
            yield
        yield endpoint.data.eq(int(i))
        yield endpoint.stb.eq(1)
        yield
        while not (yield endpoint.ack):
            yield
        yield endpoint.stb.eq(0)


@passive
def retrieve(endpoint, o, maxwait=10):
    yield
    while True:
        for _ in range(random.randint(0, maxwait)):
            yield
        yield endpoint.ack.eq(1)
        yield
        while not (yield endpoint.stb):
            yield
        o.append((yield endpoint.data))
        yield endpoint.ack.eq(0)


class TestMACFIR(unittest.TestCase):
    def test_init(self):
        dut = fir.MACFIR(n=10, scale=0)
        self.assertEqual(len(dut.sample.load.data), 24)
        self.assertEqual(len(dut.coeff.load.data), 18)
        self.assertEqual(len(dut.output.data), 48)

    def setcoeff(self, c, h):
        for i, bi in enumerate(h):
            yield c[i].eq(int(bi))

    def test_run(self):
        x = np.arange(20) + 1
        h = np.arange(10) + 1
        dut = fir.MACFIR(n=len(h), scale=0)
        o = []
        random.seed(42)
        run_simulation(dut, [self.setcoeff(dut.coeff.sr, h[::-1]),
            feed(dut.sample.load, x), retrieve(dut.output, o)])
        p = np.convolve(h, x)
        self.assertEqual(o, list(p[:len(o)]))

    def test_sym(self):
        x = np.arange(20) + 1
        h = np.arange(5) + 1
        dut = fir.SymMACFIR(n=len(h), scale=0)
        o = []
        random.seed(42)
        run_simulation(dut, [self.setcoeff(dut.coeff.sr, h[::-1]),
            feed(dut.sample.load, x), retrieve(dut.output, o)])
        hh = np.r_[h, h[::-1]]
        p = np.convolve(hh, x)
        self.assertEqual(o, list(p[:len(o)]))


class TestHBFMACUp(unittest.TestCase):
    def test_init(self):
        coeff = [-3, 0, 6, 8, 6, 0, -3]
        dut = fir.HBFMACUpsampler(coeff)
        self.assertEqual(len(dut.coeff.sr), 2)

    def test_coeff(self):
        for coeff in [0], [-1, 3, -1], [-1, 0, 1, 0, 1, 0, 1, -2]:
            with self.subTest(coeff=coeff):
                with self.assertRaises(ValueError):
                    fir.HBFMACUpsampler(coeff)

    def test_run(self):
        for n in 2, 3, 4, 10:
            coeff, x = self.coeff(n)
            with self.subTest(coeff=coeff):
                self.filter(coeff, x)
            print(n)
            #with self.subTest(coeff=coeff, maxwait=True):
            #    self.filter(coeff, x, maxwait=1)

    def coeff(self, n):
        x = np.arange(3*n) + 1
        coeff = []
        for i in range(n):
            j = i + 2
            j = (-j if j & 1 else j) << 2
            coeff[2*i:2*i] = [j, 0, j, 0]
        coeff[2*n - 1] = 1
        coeff = coeff[:-1]
        return coeff, x

    def filter(self, coeff, x, maxwait=0):
        dut = fir.HBFMACUpsampler(coeff)
        n = (len(coeff) + 1)//4
        b = log2_int(coeff[2*n - 1])
        bias = (1 << max(0, b - 1)) - 1
        self.assertEqual(dut.bias.reset.value, bias)
        o = []
        random.seed(42)
        run_simulation(dut, [feed(dut.input, x, maxwait=n*maxwait),
                             retrieve(dut.output, o, maxwait=n*maxwait//2)],
                       vcd_name="hbf.vcd")
        # first sample out is a zero sample from the center tap
        p = np.convolve(coeff, np.c_[np.zeros_like(x), x].ravel())
        # bias and rounding
        p = (p + bias) >> b
        self.assertEqual(o, list(p[:len(o)]))
