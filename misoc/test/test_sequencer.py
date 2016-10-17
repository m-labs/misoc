import unittest

from migen import *

from misoc.cores.sequencer import *


class TestSequencer(unittest.TestCase):
    def test_sequencer(self):
        program = [
            InstWrite(0, 0xaa),
            InstWrite(1, 0x55),
            InstWait(0, 0x01),
            InstWait(0, 0x10),
            InstEnd()
        ]
        dut = Sequencer(program)

        def wait():
            timeout = 0
            while not ((yield dut.bus.cyc) and (yield dut.bus.stb)):
                timeout += 1
                assert timeout < 20
                yield
            return (
                (yield dut.bus.we),
                (yield dut.bus.adr),
                (yield dut.bus.dat_w))

        def ack(data=None):
            if data is not None:
                yield dut.bus.dat_r.eq(data)
            yield dut.bus.ack.eq(1)
            yield
            yield dut.bus.ack.eq(0)
            yield

        def check():
            for inst_ip, inst in enumerate(program):
                if isinstance(inst, InstWrite):
                    we, a, d = yield from wait()
                    self.assertTrue(we)
                    self.assertEqual(a, inst.address)
                    self.assertEqual(d, inst.data)
                    yield from ack()
                elif isinstance(inst, InstWait):
                    pos_val = inst.mask
                    neg_val = 0x00
                    for _ in range(3):
                        we, a, d = yield from wait()
                        self.assertFalse(we)
                        self.assertEqual(a, inst.address)
                        yield from ack(neg_val)
                    we, a, d = yield from wait()
                    self.assertFalse(we)
                    self.assertEqual(a, inst.address)
                    yield from ack(pos_val)
                elif isinstance(inst, InstEnd):
                    for _ in range(20):
                        self.assertFalse(((yield dut.bus.cyc)
                                          and (yield dut.bus.stb)))
                    return
                else:
                    raise ValueError

        run_simulation(dut, check())
