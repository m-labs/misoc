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
        b = log2_int(r, need_pow2=False)  # bit growth
        self.input = Endpoint([("data", (width, True))])
        self.output = Endpoint([("data0", (width + n*r, True)),
                                ("data1", (width + n*r, True))])
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

        # comb stages
        for _ in range(n):
            sig0 = Signal((len(sig), True), reset_less=True)
            diff = Signal((len(sig) + 1, True), reset_less=True)
            self.sync += [
                If(comb_ce,
                    sig0.eq(sig),
                    diff.eq(sig - sig0)
                ),
            ]
            sig = diff

        # zero stuffer, gearbox, and first integrator
        sig0 = Signal((len(sig) - 1, True), reset_less=True)
        sig1 = Signal((len(sig) - 1, True))
        even = Signal()
        sum = Signal((len(sig) - 1, True))
        self.comb += [
            sum.eq(sig1 + sig),
        ]
        self.sync += [
            sig0.eq(sig1),
            If(comb_ce,
                even.eq(~even),
                If(even,
                    sig0.eq(sum),
                ),
                sig1.eq(sum),
            )
        ]

        # integrator stages
        for _ in range(n - 1):
            sum0 = Signal((len(sig0) + b - 1, True), reset_less=True)
            sum1 = Signal((len(sig0) + b - 1, True))
            self.sync += [
                If(int_ce,
                    sum0.eq(sum1 + sig0),
                    sum1.eq(sum1 + sig0 + sig1),
                )
            ]
            sig0, sig1 = sum0, sum1

        self.comb += [
            self.output.data0.eq(sig0),
            self.output.data1.eq(sig1),
        ]
