import numpy as np
import unittest
import random
from migen import *

from misoc.cores import fir


class TestDSP(unittest.TestCase):
    def setUp(self):
        self.dut = fir.DSP()

    def test_init(self):
        self.assertEqual(len(self.dut.a), 25)
        self.assertEqual(len(self.dut.b), 18)
        self.assertEqual(len(self.dut.c), 48)
        self.assertEqual(len(self.dut.d), 25)
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


class TestMACFIR(unittest.TestCase):
    def test_init(self):
        dut = fir.MACFIR(n=10)
        self.assertEqual(len(dut.sample.load.data), 25)
        self.assertEqual(len(dut.coeff.load.data), 18)
        self.assertEqual(len(dut.out.data), 48)

    def load(self, dut, h, x):
        for i, bi in enumerate(h):
            yield dut.coeff.sr[i].eq(int(bi))
        yield dut.bias.eq(0)
        yield
        for i in x:
            for _ in range(random.randint(0, 20)):
                yield
            yield dut.sample.load.data.eq(int(i))
            yield dut.sample.load.stb.eq(1)
            yield
            while not (yield dut.sample.load.ack):
                yield
            yield dut.sample.load.stb.eq(0)

    @passive
    def retrieve(self, dut, o):
        yield
        while True:
            for _ in range(random.randint(0, 20)):
                yield
            yield dut.out.ack.eq(1)
            yield
            while not (yield dut.out.stb):
                yield
            o.append((yield dut.out.data))
            yield dut.out.ack.eq(0)

    def test_run(self):
        x = np.arange(20) + 1
        h = np.arange(10) + 1
        dut = fir.MACFIR(n=len(h))
        o = []
        random.seed(42)
        run_simulation(
            dut, [self.load(dut, h[::-1], x), self.retrieve(dut, o)])
        p = np.convolve(h, x)
        self.assertEqual(o, list(p[:len(o)]))

    def test_sym(self):
        x = np.arange(20) + 1
        h = np.arange(5) + 1
        dut = fir.SymMACFIR(n=len(h))
        o = []
        random.seed(42)
        run_simulation(
            dut, [self.load(dut, h[::-1], x), self.retrieve(dut, o)])
        hh = np.r_[h, h[::-1]]
        p = np.convolve(hh, x)
        self.assertEqual(o, list(p[:len(o)]))


class TestHBFMACUp(unittest.TestCase):
    def test_init(self):
        coeff = [1, 0, -3, 0, 6, 8, 6, 0, -3, 0, 1]
        dut = fir.HBFMACUpsampler(coeff)
        self.assertEqual(len(dut.coeff.sr), 3)

    def feed(self, dut, x):
        for i in x:
            for _ in range(random.randint(0, 20)):
                yield
            yield dut.input.data.eq(int(i))
            yield dut.input.stb.eq(1)
            yield
            while not (yield dut.input.ack):
                yield
            yield dut.input.stb.eq(0)

    @passive
    def retrieve(self, dut, o):
        yield
        while True:
            for _ in range(random.randint(0, 20)):
                yield
            yield dut.output.ack.eq(1)
            yield
            while not (yield dut.output.stb):
                yield
            o.append((yield dut.output.data))
            yield dut.output.ack.eq(0)

    def test_run(self):
        x = np.arange(20) + 1
        coeff = [1, 0, -3, 0, 6, 0, -16, 32, -16, 0, 6, 0, -3, 0, 1]
        dut = fir.HBFMACUpsampler(coeff)
        o = []
        random.seed(42)
        run_simulation(
            dut, [self.feed(dut, x), self.retrieve(dut, o)], vcd_name="hbf.vcd")
        p = np.convolve(coeff, x)
        self.assertEqual(o, list(p[:len(o)]))


