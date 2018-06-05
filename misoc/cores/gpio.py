from migen import *
from migen.genlib.cdc import MultiReg

from misoc.interconnect.csr import *


class GPIOIn(Module, AutoCSR):
    def __init__(self, signal):
        self._in = CSRStatus(len(signal))
        self.specials += MultiReg(signal, self._in.status)


class GPIOOut(Module, AutoCSR):
    def __init__(self, signal, reset_out=0):
        self._out = CSRStorage(len(signal), reset=reset_out)
        self.comb += signal.eq(self._out.storage)


class GPIOTristate(Module, AutoCSR):
    def __init__(self, signals, reset_out=0, reset_oe=0):
        l = len(signals)
        self._in = CSRStatus(l)
        self._out = CSRStorage(l, reset=reset_out)
        self._oe = CSRStorage(l, reset=reset_oe)

        for n, signal in enumerate(signals):
            ts = TSTriple(1)
            self.specials += ts.get_tristate(signal)

            status = Signal()
            self.comb += self._in.status[n].eq(status)

            self.specials += MultiReg(ts.i, status)
            self.comb += [
                ts.o.eq(self._out.storage[n]),
                ts.oe.eq(self._oe.storage[n])
            ]


class Blinker(Module):
    def __init__(self, signal, divbits=26):
        counter = Signal(divbits)
        self.comb += signal.eq(counter[divbits-1])
        self.sync += counter.eq(counter + 1)
