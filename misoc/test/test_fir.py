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
        self.assertEqual(len(self.dut.drop.data), 8)

    def test_seq(self):
        def load():
            yield self.dut.drop.ack.eq(1)
            yield self.dut.load.push.eq(1)
            for i in range(10):
                for _ in range(random.randint(0, 15)):
                    yield
                yield self.dut.load.data.eq(i)
                yield self.dut.load.stb.eq(1)
                yield
                while not (yield self.dut.load.ack):
                    yield
                yield self.dut.load.stb.eq(0)

        @passive
        def retrieve(o):
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

        o = []
        random.seed(42)
        run_simulation(self.dut, [load(), retrieve(o)])
        for i, oi in enumerate(o[2:]):
            with self.subTest(i=i):
                if not oi:
                    continue
                self.assertEqual(oi, list(range(i, i + 3)))


class TestMAC(unittest.TestCase):
    def setUp(self):
        self.dut = fir.MAC(10)

    def test_init(self):
        self.assertEqual(len(self.dut.load.data), 25)
        self.assertEqual(len(self.dut.coeff.sr[0]), 18)
        self.assertEqual(len(self.dut.out.data), 48)

    def test_run(self):
        def load():
            for i, bi in enumerate(range(10)):
                yield self.dut.coeff.sr[i].eq(bi << 12)
            yield self.dut.bias.eq(0)
            yield
            for i in range(20):
                yield self.dut.load.data.eq(i << 16)
                yield self.dut.load.stb.eq(1)
                yield
                while not (yield self.dut.load.ack):
                    yield
                # yield self.dut.load.stb.eq(1)

        @passive
        def retrieve(o):
            yield self.dut.out.ack.eq(1)
            yield
            while True:
                while not (yield self.dut.out.stb):
                    yield
                o.append((yield self.dut.out.data))
                yield
                # yield self.dut.out.ack.eq(0)

        o = []
        run_simulation(self.dut, [load(), retrieve(o)], vcd_name="mac.vcd")
        h = np.arange(10) << 12
        x = np.arange(20) << 16
        p = np.convolve(h, x)
        self.assertEqual(o, list(p[:len(o)]))
