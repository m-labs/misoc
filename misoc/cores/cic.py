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
            old = Signal((w, True), reset_less=True)
            w += 1
            diff = Signal((w, True), reset_less=True)
            self.sync += [
                If(comb_ce,
                    old.eq(sig),
                    diff.eq(sig - old)
                ),
            ]
            sig = diff

        # zero stuffer, gearbox, and first integrator
        w -= 1
        sig_a = Signal((w, True), reset_less=True)
        sig_b = Signal((w, True))
        sig_i = Signal((w, True))
        even = Signal()
        self.comb += [
            sig_i.eq(sig_b + sig),
        ]
        self.sync += [
            sig_a.eq(sig_b),
            If(comb_ce,
                even.eq(~even),
                If(even,
                    sig_a.eq(sig_i),
                ),
                sig_b.eq(sig_i),
            )
        ]

        # integrator stages
        for _ in range(n - 1):
            sig_a0 = Signal((ceil(w), True), reset_less=True)
            sum_ab = Signal((ceil(w) + 1, True), reset_less=True)
            w += b - 1
            sum_a = Signal((ceil(w), True), reset_less=True)
            sum_b = Signal((ceil(w), True))
            self.sync += [
                If(int_ce,
                    sig_a0.eq(sig_a),
                    sum_ab.eq(sig_a + sig_b),
                    sum_a.eq(sum_b + sig_a0),
                    sum_b.eq(sum_b + sum_ab),
                )
            ]
            sig_a, sig_b = sum_a, sum_b

        assert ceil(w) == len(self.output.data0)

        self.comb += [
            self.output.data0.eq(sig_a),
            self.output.data1.eq(sig_b),
        ]
