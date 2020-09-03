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
    time order"""
    def __init__(self, depth, width):
        assert depth > 1
        self.load = Endpoint([("data", width), ("push", 1)])
        self.out = Endpoint([("data", width)])
        self.out.data.reset_less = True
        self.drop = Endpoint([("data", width)])
        self.drop.ack.reset = 1

        self.sr = [Signal(width, reset_less=True) for _ in range(depth)]
        q = Signal(depth + 1, reset=1)  # one-hot output pointer
        self.comb += [
            self.out.stb.eq(~q[0]),
            self.out.eop.eq(q[1]),
            self.load.ack.eq((q[0] | (q[1] & self.out.ack)) & self.drop.ack),
            self.drop.stb.eq(self.load.stb),
            self.drop.data.eq(self.sr[-1]),
        ]
        self.sync += [
            If(self.out.stb & self.out.ack,
                # output next
                [
                    If(qi,
                        self.out.data.eq(sri)
                    )
                    for qi, sri in zip(q[2:], self.sr)
                ],
                q.eq(q[1:]),
            ),
            If(self.load.stb & self.load.ack,
                # load new low, drop/output old high
                If(self.load.push,
                    Cat(self.sr).eq(Cat(self.load.data, self.sr)),
                    self.out.data.eq(self.sr[-2]),
                ).Else(
                    self.out.data.eq(self.sr[-1]),
                ),
                q.eq(1 << depth),
            ),
        ]


class MemStorage(Module):
    """Shift-register style coefficient/sample storage.

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
        self.submodules.coeff = SRStorage(n, (len(self.dsp.b), True))
        self.submodules.data = SRStorage(n, width)
        self.load = self.data.load
        self.drop = self.data.drop
        self.out = Endpoint([("data", (len(self.dsp.pr), True))])
        self.add = Endpoint([("data", width)])
        self.bias = Signal.like(self.dsp.c)

        p_dsp = 3
        q = Signal(p_dsp + 1, reset=1)
        e = Signal(p_dsp)
        ack_dsp = Signal()
        self.sync += [
            ack_dsp.eq(~self.out.stb | self.out.ack),
            If(ack_dsp,
                q.eq(Cat(self.data.out.stb, q)),
                e.eq(Cat(self.data.out.eop, e)),
            ),
        ]
        self.comb += [
            self.load.push.eq(1),
            self.dsp.a.eq(self.data.out.data),
            self.data.out.ack.eq(ack_dsp),
            self.data.drop.ack.eq(1),  # default
            self.coeff.drop.ack.eq(1),  # default
            self.coeff.load.stb.eq(self.data.load.stb),
            self.coeff.load.push.eq(0),
            self.dsp.b.eq(self.coeff.out.data),
            self.dsp.ceb0.eq(self.coeff.out.stb),
            self.coeff.out.ack.eq(1),
            self.dsp.d.eq(self.add.data),
            self.add.ack.eq(ack_dsp),  # ignore stb
            self.dsp.presub.eq(0),
            self.dsp.cead0.eq(self.data.out.stb),
            self.dsp.cem0.eq(q[0]),
            self.dsp.cep0.eq(q[1] & ack_dsp),
            self.out.data.eq(self.dsp.pr),
            self.out.stb.eq(q[2] & e[2]),  # ignore ack
            If(self.out.stb & self.out.ack,
                self.dsp.c.eq(self.bias),
            ).Else(
                self.dsp.c.eq(self.dsp.pr),
            ),
        ]
