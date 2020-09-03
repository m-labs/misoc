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
    emitted. `out.data` is dropped from storage on load with `load.eop` set."""
    def __init__(self, depth, width, drop=True, old_first=True):
        self.load = Endpoint([("data", width)])
        self.out = Endpoint([("data", width)])

        # old first
        self.sr = [Signal(width, reset_less=True)
                   for _ in range(depth - 1 if drop else depth)]
        q = Signal(depth, reset=1)  # one-hot state

        self.comb += [
            self.load.ack.eq(self.out.ack & q[0]),
            self.out.data.eq(self.sr[0]),
            self.out.stb.eq(self.load.stb | ~q[0]),
            self.out.eop.eq(q[-1]),
        ]
        self.sync += [
            If(self.out.stb & self.out.ack,
                Cat(self.sr).eq(Cat(self.sr[1:], self.sr[0])),
                q.eq(Cat(q[-1], q)),
            ),
            If(self.load.stb & self.load.ack & ~self.load.eop,
                self.sr[-1].eq(self.load.data),
            ),
        ]


class MemStorage(Module):
    """Memory style coefficient/sample storage.

    Loads a new word, discards the oldest, and emits the entire storage in
    time order"""
    def __init__(self, n, width):
        pass


class MAC(Module):
    def __init__(self, n, pipe=None, **kwargs):
        if pipe is None:
            pipe = dict(a=0, b=1, c=0, d=0, ad=1, m=1, p=1)
        self.submodules.dsp = DSP(pipe=pipe, **kwargs)
        width = len(self.dsp.a), True
        self.submodules.coeff = SRStorage(
            n, (len(self.dsp.b), True), drop=False)
        self.submodules.sample = SRStorage(n, width)
        self.out = Endpoint([("data", (len(self.dsp.pr), True))])
        self.add = Endpoint([("data", width)])
        self.bias = Signal.like(self.dsp.c)

        p_dsp = 3
        q = Signal(p_dsp)
        ack_dsp = Signal()
        self.sync += [
            If(ack_dsp,
                q.eq(Cat(self.sample.out.eop, q)),
            ),
        ]
        self.comb += [
            self.coeff.load.eop.eq(1),
            self.coeff.load.stb.eq(self.sample.load.stb),  # ignore ack

            ack_dsp.eq(self.sample.out.stb & (~self.out.stb | self.out.ack)),

            self.sample.out.ack.eq(ack_dsp),
            self.add.ack.eq(ack_dsp),  # ignore stb
            self.coeff.out.ack.eq(ack_dsp),  # ignore stb

            self.dsp.a.eq(self.sample.out.data),
            self.dsp.d.eq(self.add.data),
            self.dsp.presub.eq(0),
            self.dsp.cead0.eq(ack_dsp),
            self.dsp.b.eq(self.coeff.out.data),
            self.dsp.ceb0.eq(ack_dsp),
            If(q[2],
                self.dsp.c.eq(self.bias),
            ).Else(
                self.dsp.c.eq(self.dsp.pr),
            ),
            self.dsp.cem0.eq(ack_dsp),
            self.dsp.cep0.eq(ack_dsp),

            self.out.data.eq(self.dsp.pr),
            self.out.stb.eq(q[2]),
        ]
