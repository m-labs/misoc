from migen import *
from misoc.interconnect.stream import Endpoint


class DSP(Module):
    """DSP multiplier abstraction

    `p = (a +- d)*b + c`

    Includes configurable number of pipeline stages each with a (common)
    reset and individual clock enables. This models the typical DSP block
    with multiplier, pre-adder and post-adder. It can be used for different
    architectures.

    :param pipe: Dictionary with length of pipeline registers to add.
    :param width: Dictionary with signal widths.
    """
    def __init__(self, pipe=None, width=None):
        if pipe is None:
            pipe = dict(a=0, b=0, c=0, d=0, ad=1, m=1, p=1)
        if width is None:
            width = dict(a=24, b=18, c=48, d=24, ad=25, m=48, p=48)

        for reg, width in width.items():
            self._make_pipe_reg(reg, width, pipe.get(reg, 0))
        self.presub = Signal()
        self.postsub = Signal()

        self.comb += [
            If(self.presub,
                self.ad.eq(self.ar - self.dr),
            ).Else(
                self.ad.eq(self.ar + self.dr),
            ),
            self.m.eq(self.adr*self.br),
            If(self.postsub,
                self.p.eq(self.cr - self.mr),
            ).Else(
                self.p.eq(self.cr + self.mr),
            ),
        ]

    def _make_pipe_reg(self, reg, width, pipe, reset=0):
        sig = Signal((width, True), reset_less=True, reset=reset, name=reg)
        setattr(self, reg, sig)
        rst = Signal(name="rst{}".format(reg))
        setattr(self, "rst{}".format(reg), rst)
        for i in range(pipe):
            sig, pre = Signal.like(sig, name="{}r".format(reg)), sig
            ce = Signal(reset=1, name="ce{}{}".format(reg, i))
            setattr(self, "ce{}{}".format(reg, i), ce)
            self.sync += [
                If(ce,
                    sig.eq(pre),
                ),
                If(rst,
                    sig.eq(sig.reset),
                ),
            ]
        setattr(self, "{}r".format(reg), sig)


class SRStorage(Module):
    """Shift-register style coefficient/sample storage.

    Loads a new word, discards the oldest, and emits the entire storage in
    time order.
    """
    def __init__(self, depth, width, mode="old-first"):
        self.load = Endpoint([("data", width)])
        self.out = Endpoint([("data", width)])

        self.sr = [Signal(width, reset_less=True) for _ in range(
            depth - 1 if mode == "old-first" else depth)]
        q = Signal(depth, reset=1)  # one-hot state

        # SR Storage time sequences for depth=4, different modes:
        #
        # old-first
        # load sr   out
        # -------------
        # d    abc a   stb+ack, eop
        #      bcd b
        #      cdb c
        #      dbc d
        #      bcd b   wait
        #
        # circular
        # sr   out
        # --------
        # abcd a  stb+ack, !eop
        # bcda b
        # cdab c
        # dabc d
        # abcd a  wait
        #
        # new-first
        # load buf sr   out
        # -----------------
        # e        dcba d  stb+ack, eop
        #      e   cbad c
        #      e   badc b
        #      e   adcb a
        # f        edcb e  wait

        self.comb += [
            self.load.ack.eq(self.out.ack & q[0]),
            self.out.data.eq(self.sr[0]),
            self.out.stb.eq(self.load.stb | ~q[0]),
            self.out.eop.eq(q[-1]),
        ]
        self.sync += [
            If(self.out.stb & self.out.ack,
                q.eq(Cat(q[-1], q)),
            ),
        ]
        if mode in ("old-first", "circular"):
            self.sync += [
                If(self.out.stb & self.out.ack,
                    Cat(self.sr).eq(Cat(self.sr[1:], self.sr[0])),
                )
            ]
            if mode == "old-first":
                self.sync += [
                    If(self.load.stb & self.load.ack & self.load.eop,
                        self.sr[-1].eq(self.load.data),
                    ),
                ]
        elif mode == "new-first":
            buf = Signal.like(self.sr[0])
            self.sync += [
                If(self.out.stb & self.out.ack,
                    If(self.out.eop,
                        self.sr[0].eq(buf)
                    ).Else(
                        Cat(self.sr).eq(Cat(self.sr[1:], self.sr[0])),
                    ),
                ),
                If(self.load.stb & self.load.ack & self.load.eop,
                    buf.eq(self.load.data),
                )
            ]
        else:
            raise ValueError()


class MemStorage(Module):
    """Memory style coefficient/sample storage.

    Loads a new word, discards the oldest, and emits the entire storage in
    time order"""
    def __init__(self, depth, width, mode="old-first"):
        # Mem Storage time sequences for depth=4, different modes:
        #
        # old-first
        # load mem addr out
        # -----------------
        # d    abc 0    a   stb+ack, eop
        #      dbc 1    b
        #      dbc 2    c
        #      dbc 0    d
        #      dbc 1    b   wait
        #
        # circular
        # mem  addr out
        # -------------
        # abcd 0    a  stb+ack, !eop
        # abcd 1    b
        # abcd 2    c
        # abcd 3    d
        # abcd 0    a  wait
        #
        # new-first
        # load buf mem  addr out
        # -----------------------
        # e        dcba 0    d  stb+ack, eop
        #      e   dcba 1    c
        #      e   dcba 2    b
        #      e   dcba 3    a
        # f        dcbe 3    e  wait
        raise NotImplementedError


class MACFIR(Module):
    """Multiply-accumulate FIR filter.

    Sample and coefficient storage is implemented using `SRStorage`. Load
    coefficients either into `coeff.sr[:]` statically or load one new
    coefficient per input sample to reconfigure the filter (see `SRStorage for
    details on the protocol).

    The DSP module uses full pipelining.

    Multiple `MACFIR` can be cascaded in a systolic arrangement for higher
    throughput.
    """
    def __init__(self, n, scale, **kwargs):
        pipe = dict(a=1, b=2, c=0, d=1, ad=1, m=1, p=1)
        self.submodules.dsp = DSP(pipe=pipe, **kwargs)
        width = len(self.dsp.a), True
        self.submodules.coeff = SRStorage(
            n, (len(self.dsp.b), True), mode="circular")
        self.submodules.sample = SRStorage(n, width, mode="old-first")
        self.out = Endpoint([("data", (len(self.dsp.pr), True))])
        self.bias = Signal.like(self.dsp.c, reset=(1 << max(0, scale - 1)) - 1)

        p_dsp = 4  # a/d/b0, ad/b1, m, p
        q = Signal(p_dsp)
        ack_dsp = Signal()
        self.sync += [
            If(ack_dsp,
                q.eq(Cat(self.sample.out.eop, q)),
            ),
        ]
        self.comb += [
            self.sample.load.eop.eq(1),

            self.coeff.load.stb.eq(self.sample.load.stb),  # ignore ack

            ack_dsp.eq(self.sample.out.stb & (~self.out.stb | self.out.ack)),

            self.sample.out.ack.eq(ack_dsp),
            self.coeff.out.ack.eq(ack_dsp),  # ignore stb

            self.dsp.a.eq(self.sample.out.data),
            self.dsp.cea0.eq(ack_dsp),
            self.dsp.ced0.eq(ack_dsp),
            self.dsp.cead0.eq(ack_dsp),
            self.dsp.b.eq(self.coeff.out.data),
            self.dsp.ceb0.eq(ack_dsp),
            self.dsp.ceb1.eq(ack_dsp),
            If(q[-1],
                self.dsp.c.eq(self.bias),
            ).Else(
                self.dsp.c.eq(self.dsp.pr),
            ),
            self.dsp.cem0.eq(ack_dsp),
            self.dsp.cep0.eq(ack_dsp),

            self.out.data.eq(self.dsp.pr >> scale),
            self.out.stb.eq(q[-1]),
        ]


class SymMACFIR(MACFIR):
    """Symmetric coefficient multiply-accumulate FIR filter

    Load the short delay side coefficients (with +1 delay tap first) into
    `coeff`.

    The center tap sample is available at `sample.out` during the
    `sample.load` phase.

    There is no coefficient for the center tap here. This allows efficient
    implementation of half band interpolation filters in polyphase style
    where this is the heavy computation bank and the center tap coefficient
    is the identity.

    To support an array of multiple systolic symmetric MAC FIR blocks (to
    increase throughput), the `sample`->`sym` connection should be overridden.
    """
    def __init__(self, n, scale, **kwargs):
        super().__init__(n, scale, **kwargs)
        self.submodules.sym = SRStorage(
            n, (len(self.dsp.d), True), mode="new-first")
        self.comb += [
            self.sym.load.eop.eq(1),
            self.sym.load.data.eq(self.sample.out.data),
            self.sym.load.stb.eq(self.sample.load.stb),  # ignore ack
            self.sym.out.ack.eq(self.sample.out.ack),  # ignore stb
            self.dsp.d.eq(self.sym.out.data),
            self.dsp.presub.eq(0),
        ]


class HBFMACUpsampler(SymMACFIR):
    def __init__(self, coeff, **kwargs):
        n = (len(coeff) + 1)//4
        if len(coeff) != n*4 - 1:
            raise ValueError("HBF length must be 4*n-1", coeff)
        elif n < 2:
            raise ValueError("Need order n >= 2")
        for i, c in enumerate(coeff):
            if i == n*2 - 1:
                if not c:
                    raise ValueError("HBF center tap must not be zero")
                scale = log2_int(c)
            elif i & 1:
                if c:
                    raise ValueError("HBF even taps must be zero", (i, c))
            elif not c:
                raise ValueError("HBF needs odd taps", (i, c))
            elif c != coeff[-1 - i]:
                raise ValueError("HBF must be symmetric", (i, c))

        super().__init__(n=n, scale=scale, **kwargs)
        # TODO maybe MSB align and increase scale
        logh = 0
        for i, c in enumerate(coeff[n*2::2]):
            self.coeff.sr[i].reset = c << logh

        width = len(self.dsp.a)
        self.input = Endpoint([("data", (width, True))])
        self.output = Endpoint([("data", (width, True))])

        even = Signal(reset=1)
        p_dsp = 4
        buf = [Signal.like(self.sample.sr[0])
                for i in range(max(1 + p_dsp//n, 1))]
        self.comb += [
            self.sample.load.data.eq(self.input.data),
            self.sample.load.stb.eq(self.input.stb),
            self.input.ack.eq(self.sample.load.ack),

            # marks the end of an interpolation pair
            self.output.eop.eq(~even),
            self.output.data.eq(Mux(
                even, self.out.data, buf[-1])),
            self.output.stb.eq(self.out.stb | ~even),
            self.out.ack.eq(even & self.output.ack),
        ]
        self.sync += [
            If(self.output.stb & self.output.ack,
                even.eq(~even),
                If(~even,
                    Cat(buf[1:]).eq(Cat(buf)) if len(buf) > 1 else []
                ),
            ),
            If(self.input.stb & self.input.ack,
                # tap the center sample
                buf[0].eq(self.sample.out.data)
            ),
        ]
