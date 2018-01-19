from migen import *
from migen.genlib.cdc import MultiReg

from misoc.interconnect.csr import AutoCSR, CSR, CSRStorage, CSRStatus


class SlaveFPGA(Module, AutoCSR):
    def __init__(self, io):
        self._program = CSRStorage()
        self._done = CSRStatus()
        self._error = CSRStatus()

        self._divisor = CSRStorage(32)
        self._data = CSRStorage(32)
        self._start = CSR()
        self._busy = CSRStatus()

        # # #

        ctr = Signal.like(self._divisor.storage)
        clk2x = Signal()
        self.comb += [
            clk2x.eq(ctr == 0),
        ]
        self.sync += [
            If(ctr == 0,
                ctr.eq(self._divisor.storage)
            ).Else(
                ctr.eq(ctr - 1)
            )
        ]

        shreg = Signal.like(self._data.storage)
        bits = Signal(max=shreg.nbits)
        busy = Signal()
        clk = Signal()
        self.comb += [
            busy.eq(bits != 0),
            self._busy.status.eq(busy)
        ]
        self.sync += [
            If(self._start.re & self._start.r,
                clk.eq(0),
                bits.eq(shreg.nbits - 1),
                shreg.eq(self._data.storage)
            ).Elif(clk2x & busy,
                clk.eq(~clk),
                If(clk,
                    bits.eq(bits - 1),
                    shreg.eq(shreg >> 1)
                )
            )
        ]

        self.sync += [
            io.program_b.eq(~self._program.storage),
            io.din.eq(shreg[0]),
            io.cclk.eq(clk)
        ]
        self.specials += [
            MultiReg(io.done, self._done.status),
            MultiReg(~io.init_b, self._error.status)
        ]


class _TestIO(Module):
    def __init__(self):
        self.done = Signal()
        self.program_b = Signal()
        self.init_b = Signal()
        self.din = Signal()
        self.cclk = Signal()


def _test(io, dut):
    data = 0x8fffaaa1
    yield from dut._divisor.write(3)
    yield from dut._data.write(data)
    yield from dut._start.write(1)
    yield
    while (yield from dut._busy.read()):
        assert (yield io.cclk) == 0
        yield; yield; yield; yield
        assert (yield io.cclk) == 1
        assert (yield io.din) == (data & 1)
        yield; yield; yield; yield
        data >>= 1
    for _ in range(4):
        assert (yield io.cclk) == 0
        yield; yield; yield; yield


if __name__ == '__main__':
    io = _TestIO()
    dut = SlaveFPGA(io)
    run_simulation(dut, _test(io, dut), vcd_name="slave_fpga.vcd")
