from math import ceil, log2

from migen import *
from misoc.interconnect.stream import Endpoint


class SuperCIC(Module):
    """Super-sample CIC interpolator.

    This is an implementation for a specific interpolation case of
    "S/R -> S/1" samples per cycle with S=2 (M=1 delay, N order, R rate change)
    in the usual notation.

    * R can be odd.
    * It can be generalized to any S.
    * There is no handshaking between the input and output domains and no
      backward or forward pressure. R is only used to compute bit growth
      guard width.
    * The output has gain R**(N - 1).
    """
    def __init__(self, n, r, width):
        if n < 1:
            raise ValueError()
        b = log2(r)  # bit growth
        self.input = Endpoint([("data", (width, True))])
        self.output = Endpoint([("data0", (width + ceil((n - 1)*b), True)),
                                ("data1", (width + ceil((n - 1)*b), True))])
        comb_ce = Signal()
        int_ce = Signal()
        self.comb += [
            self.input.ack.eq(1),
            comb_ce.eq(self.input.stb & self.input.ack),
            self.output.stb.eq(1),
            int_ce.eq(self.output.stb & self.output.ack)
        ]

        sig = self.input.data
        sig.reset_less = True

        w = len(sig)
        # comb stages
        for _ in range(n):
            sig0 = Signal((w, True), reset_less=True)
            w += 1
            diff = Signal((w, True), reset_less=True)
            self.sync += [
                If(comb_ce,
                    sig0.eq(sig),
                    diff.eq(sig - sig0)
                ),
            ]
            sig = diff

        # zero stuffer, gearbox, and first integrator
        w -= 1
        sig0 = Signal((w, True), reset_less=True)
        sig1 = Signal((w, True))
        even = Signal()
        sig11 = Signal((w, True))
        self.comb += [
            sig11.eq(sig1 + sig),
        ]
        self.sync += [
            sig0.eq(sig1),
            If(comb_ce,
                even.eq(~even),
                If(even,
                    sig0.eq(sig11),
                ),
                sig1.eq(sig11),
            )
        ]

        # integrator stages
        for _ in range(n - 1):
            sig00 = Signal((ceil(w), True), reset_less=True)
            sum01 = Signal((ceil(w) + 1, True), reset_less=True)
            w += b - 1
            sum0 = Signal((ceil(w), True), reset_less=True)
            sum1 = Signal((ceil(w), True))
            self.sync += [
                If(int_ce,
                    sig00.eq(sig0),
                    sum01.eq(sig0 + sig1),
                    sum0.eq(sum1 + sig00),
                    sum1.eq(sum1 + sum01),
                )
            ]
            sig0, sig1 = sum0, sum1

        assert ceil(w) == len(self.output.data0), (w, len(self.output.data0))

        self.comb += [
            self.output.data0.eq(sig0),
            self.output.data1.eq(sig1),
        ]
