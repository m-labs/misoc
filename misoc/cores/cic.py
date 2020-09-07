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
            sig0 = Signal.like(self.input.data)
            self.sync += [
                If(comb_ce,
                    sig0.eq(sig)
                )
            ]
            c = Signal((len(sig) + 1, True), reset_less=True)
            self.comb += c.eq(sig - sig0)
            sig = c

        # zero stuffing gearbox and first integrator
        sig0 = Signal((len(sig) - 1, True), reset_less=True)
        sig1 = Signal((len(sig) - 1, True))
        even = Signal()
        self.sync += [
            sig0.eq(sig1),
            If(comb_ce,
                even.eq(~even),
                If(even,
                    sig0.eq(sig1 + sig),
                ),
                sig1.eq(sig1 + sig),
            )
        ]

        # integrator stages
        for _ in range(n - 1):
            i0 = Signal((len(sig0) + b - 1, True), reset_less=True)
            i1 = Signal((len(sig0) + b - 1, True))
            self.sync += [
                If(int_ce,
                    i0.eq(i1 + sig0),
                    i1.eq(i1 + sig0 + sig1),
                )
            ]
            sig0, sig1 = i0, i1

        self.comb += [
            self.output.data0.eq(sig0),
            self.output.data1.eq(sig1),
        ]
