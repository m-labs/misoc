from migen import *
from migen.genlib.cdc import MultiReg

from misoc.interconnect.csr import *


class GPIOIn(Module, AutoCSR):
    def __init__(self, signal):
        self._in = CSRStatus(len(signal))
        self.specials += MultiReg(signal, self._in.status)


class GPIOOut(Module, AutoCSR):
    def __init__(self, signal):
        self._out = CSRStorage(len(signal))
        self.comb += signal.eq(self._out.storage)


class GPIOTristate(Module, AutoCSR):
    def __init__(self, signals):
        l = len(signals)
        self._in = CSRStatus(l)
        self._out = CSRStorage(l)
        self._oe = CSRStorage(l)

        for n, signal in enumerate(signals):
            ts = TSTriple(1)
            self.specials += ts.get_tristate(signal)

            self.specials += MultiReg(ts.i, self._in.status)
            self.comb += [
                ts.o.eq(self._out.storage),
                ts.oe.eq(self._oe.storage)
            ]


class Blinker(Module):
    def __init__(self, signal, divbits=26):
        counter = Signal(divbits)
        self.comb += signal.eq(counter[divbits-1])
        self.sync += counter.eq(counter + 1)
