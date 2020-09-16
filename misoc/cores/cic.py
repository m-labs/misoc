from math import ceil, log2

from migen import *
from misoc.interconnect.stream import Endpoint


class SuperCIC(Module):
    """Super-sample CIC interpolator.

    This is an implementation for a specific interpolation case of
    "S/R -> S/1" samples per cycle with S=2 (M=1 delay, N order, R rate change)
    in the usual notation.

    * R can be odd.
    * It can be generalized to any S and to S/T output rate
    * The output has gain R**(N - 1).
    """
    def __init__(self, n, r, width):
        if n < 1:
            raise ValueError()
        s = 2
        # m = 1
        b = log2(r)  # bit growth
        self.input = Endpoint([("data", (width, True))])
        self.output = Endpoint([("data0", (width + ceil((n - 1)*b), True)),
                                ("data1", (width + ceil((n - 1)*b), True))])
        comb_ce = Signal()
        int_ce = Signal()
        i = Signal(max=r)

        self.comb += [
            self.input.ack.eq((i == 0) | (i == r//s)),
            comb_ce.eq(self.input.stb & self.input.ack),
            self.output.stb.eq(1),
            int_ce.eq(self.output.stb & self.output.ack)
        ]

        self.sync += [
            If(int_ce,
                i.eq(i + 1),
                If(i == r - 1,
                    i.eq(0),
                ),
            )
        ]

        sig = self.input.data
        sig.reset_less = True

        width = len(sig)
        # comb stages, one pipeline stage each
        for _ in range(n):
            old = Signal((width, True), reset_less=True)
            width += 1
            diff = Signal((width, True), reset_less=True)
            self.sync += [
                If(comb_ce,
                    old.eq(sig),
                    diff.eq(sig - old)
                ),
            ]
            sig = diff

        # zero stuffer, gearbox, and first integrator, one pipeline stage
        width -= 1
        sig_a = Signal((width, True), reset_less=True)
        sig_b = Signal((width, True))
        sig_i = Signal((width, True))
        self.comb += [
            sig_i.eq(sig_b + sig),
        ]
        self.sync += [
            sig_a.eq(sig_b),
            If(comb_ce,
                If(i == 0,
                    sig_a.eq(sig_i),
                ),
                sig_b.eq(sig_i),
            )
        ]

        # integrator stages, two pipeline stages each
        for _ in range(n - 1):
            sig_a0 = Signal((ceil(width), True), reset_less=True)
            sum_ab = Signal((ceil(width) + 1, True), reset_less=True)
            width += b - 1
            sum_a = Signal((ceil(width), True), reset_less=True)
            sum_b = Signal((ceil(width), True))
            self.sync += [
                If(int_ce,
                    sig_a0.eq(sig_a),
                    sum_ab.eq(sig_a + sig_b),
                    sum_a.eq(sum_b + sig_a0),
                    sum_b.eq(sum_b + sum_ab),
                )
            ]
            sig_a, sig_b = sum_a, sum_b

        assert ceil(width) == len(self.output.data0)

        self.comb += [
            self.output.data0.eq(sig_a),
            self.output.data1.eq(sig_b),
        ]
