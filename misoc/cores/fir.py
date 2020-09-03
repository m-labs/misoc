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
            width = dict(a=25, b=18, c=48, d=25, ad=25, m=48, p=48)

        for reg, width in width.items():
            self._make_pipe_reg(reg, width, pipe.get(reg, 0))
        self.presub = Signal()

        self.comb += [
            If(self.presub,
                self.ad.eq(self.ar - self.dr),
            ).Else(
                self.ad.eq(self.ar + self.dr),
            ),
            self.m.eq(self.adr*self.br),
            self.p.eq(self.mr + self.cr),
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

    `load.eop` used to indicate no new data to be shifted in but storage to be
    emitted. `out.data` is dropped storage on load with `load.eop` set."""
    def __init__(self, depth, width, drop=True, old_first=True):
        self.load = Endpoint([("data", width)])
        self.out = Endpoint([("data", width)])

        self.sr = [Signal(width, reset_less=True)
                   for _ in range(depth - 1 if drop and old_first else depth)]
        q = Signal(depth, reset=1)  # one-hot state

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
        if old_first:
            self.sync += [
                If(self.out.stb & self.out.ack,
                    Cat(self.sr).eq(Cat(self.sr[1:], self.sr[0])),
                ),
                If(self.load.stb & self.load.ack & self.load.eop,
                    self.sr[-1].eq(self.load.data),
                ),
            ]
        else:
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


class MemStorage(Module):
    """Memory style coefficient/sample storage.

    Loads a new word, discards the oldest, and emits the entire storage in
    time order"""
    def __init__(self, n, width):
        pass


class MACFIR(Module):
    """Multiply-accumulate FIR filter.

    Sample and coefficient storage is implemented using `SRStorage`.
    Load coefficients either into `coeff.sr[:]` statically or load one new
    coefficient per input sample to reconfigure the filter (see `SRStorage for details
    on the protocol).

    The DSP module uses full pipelining.
    """
    def __init__(self, n, **kwargs):
        pipe = dict(a=1, b=2, c=0, d=1, ad=1, m=1, p=1)
        self.submodules.dsp = DSP(pipe=pipe, **kwargs)
        width = len(self.dsp.a), True
        self.submodules.coeff = SRStorage(
            n, (len(self.dsp.b), True), drop=False)
        self.submodules.sample = SRStorage(n, width)
        self.out = Endpoint([("data", (len(self.dsp.pr), True))])
        self.bias = Signal.like(self.dsp.c)

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

            self.out.data.eq(self.dsp.pr),
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
    def __init__(self, n, **kwargs):
        super().__init__(n, **kwargs)
        self.submodules.sym = SRStorage(
            n, (len(self.dsp.d), True), old_first=False)
        self.comb += [
            self.sym.load.eop.eq(1),
            self.sym.load.data.eq(self.sample.out.data),
            self.sym.load.stb.eq(self.sample.load.stb),  # ignore ack
            self.sym.out.ack.eq(self.sample.out.ack),  # ignore stb
            self.dsp.d.eq(self.sym.out.data),
            self.dsp.presub.eq(0),
        ]
