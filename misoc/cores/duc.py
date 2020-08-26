from migen import *
from misoc.interconnect.stream import Endpoint
from migen.genlib.fsm import FSM

from .cossin import CosSinGen


def complex(width):
    """Complex integer layout"""
    return [("i", (width, True)), ("q", (width, True))]


def eqh(lhs, rhs):
    """MSB aligned assignment.
    Returns statement to be added to comb/sync context."""
    shift = len(lhs) - len(rhs)
    if shift > 0:
        return lhs[shift:].eq(rhs)
    elif shift < 0:
        return lhs.eq(rhs[-shift:])
    else:
        return lhs.eq(rhs)


def pipe(lhs, rhs, n):
    """Assign rhs to lhs through n reset_less pipeline registers.
    Returns list of statements to be added to sync context."""
    assert n > 0
    stmts = []
    w = min(len(lhs), len(rhs))
    for i in range(n - 1):
        pip, rhs = rhs, Signal(n, reset_less=True)
        stmts.append(rhs.eq(pip))
    stmts.append(lhs.eq(rhs))
    return stmts


class ComplexMultiplier(Module):
    def __init__(self, awidth=16, bwidth=None, pwidth=None):
        """
        Complex multiplier, with full pipelining, using 3 DSP, rounding

        `p.i + 1j*p.q = (a.i + 1j*a.q)*(b.i + 1j*b.q)`

        Output scaling and rounding for `pwidth < awidth + bwidth + 1`:
        * Rounding is "round half down".
        * If `|a| <= (1 << awidth - 1) - 1`, or
            `|b| <= (1 << bwidth - 1) - 1`, then
            `p.i`, `p.q`, |p| will be valid.
        * Ensure that |a| and |b| are in range and not just their
          quadratures.
        * That range excludes the components' (negative) minimum of at least
          one input, that input's unit circle, and the area outside the unit
          circles of both inputs.
        """
        if bwidth is None:
            bwidth = awidth
        if pwidth is None:
            # worst case min*min+min*min
            pwidth = awidth + bwidth + 1
        self.a = Record(complex(awidth), reset_less=True)  # 5
        self.b = Record(complex(bwidth), reset_less=True)  # 5
        self.p = Record(complex(pwidth), reset_less=True)

        # with rounding the worst case is assumed (!) to be max*max
        # (unit circle interior: 2 bit smaller than full width worst
        # case above)
        bias_bits = max(0, (awidth + bwidth - 1) - pwidth)
        # rounding bias constant
        # we don't implement more complicated rounding (even/odd) because
        # doing so looks like it might not fit into the DSPs and
        # due to the typically large shift the remaining bias is small.
        bias = (1 << bias_bits - 1) - 1 if bias_bits > 0 else 0

        ai = [Signal((awidth, True), reset_less=True) for _ in range(3)]
        aq = [Signal((awidth, True), reset_less=True) for _ in range(3)]
        bi = [Signal((bwidth, True), reset_less=True) for _ in range(2)]
        bq = [Signal((bwidth, True), reset_less=True) for _ in range(2)]
        ad = Signal((awidth + 1, True), reset_less=True)
        bs = Signal((bwidth + 1, True), reset_less=True)
        bd = Signal((bwidth + 1, True), reset_less=True)
        # these needs yet another (temporary) bit since the synthesizer
        # usually doesn't prove the cancellation
        m = [Signal((awidth + bwidth + 2, True), reset_less=True)
             for _ in range(8)]
        self.sync += [
            Cat(ai).eq(Cat(self.a.i, ai)),  # 1-3
            Cat(aq).eq(Cat(self.a.q, aq)),  # 1-3
            Cat(bi).eq(Cat(self.b.i, bi)),  # 1-2
            Cat(bq).eq(Cat(self.b.q, bq)),  # 1-2
            ad.eq(self.a.i + self.a.q),  # 1
            m[0].eq(ad*bi[0]),  # 2
            m[1].eq(m[0] + bias),  # 3
            bs.eq(bi[1] + bq[1]),  # 3
            bd.eq(bi[1] - bq[1]),  # 3
            m[2].eq(bs*aq[2]),  # 4
            m[3].eq(bd*ai[2]),  # 4
            m[4].eq(m[1]),  # 4
            m[5].eq(m[1]),  # 4
            m[6].eq(m[4] - m[2]),  # 5
            m[7].eq(m[5] - m[3]),  # 5
        ]
        self.comb += [
            self.p.i.eq(m[6][bias_bits:]),
            self.p.q.eq(m[7][bias_bits:]),
        ]
        self.latency = 5


class Accu(Module):
    """Phase accumulator, with frequency, phase offset and clear"""
    def __init__(self, fwidth, pwidth):
        self.f = Signal(fwidth)  # 2
        self.p = Signal(pwidth)  # 1
        self.clr = Signal(reset=1)  # 2
        self.z = Signal(pwidth, reset_less=True)
        # reset by clr
        q = Signal(fwidth, reset_less=True)
        self.sync += [
            q.eq(q + self.f),
            If(self.clr,
                q.eq(0),
            ),
            self.z.eq(self.p + q[-pwidth:]),
        ]


class MCM(Module):
    """Multiple constant multiplication

    Multiplies the input by multiple small constants.
    """
    def __init__(self, width, constants):
        n = len(constants)
        self.i = i = Signal(width, reset_less=True)  # 1
        self.o = o = [Signal.like(self.i) for i in range(n)]

        ###

        # TODO: improve MCM
        assert n <= 9
        assert range(n) == constants

        ctx = self.comb
        if n > 0:
            ctx += o[0].eq(0)
        if n > 1:
            ctx += o[1].eq(i)
        if n > 2:
            ctx += o[2].eq(i << 1)
        if n > 3:
            ctx += o[3].eq(i + (i << 1))
        if n > 4:
            ctx += o[4].eq(i << 2)
        if n > 5:
            ctx += o[5].eq(i + (i << 2))
        if n > 6:
            ctx += o[6].eq(o[3] << 1)
        if n > 7:
            ctx += o[7].eq((i << 3) - i)
        if n > 8:
            ctx += o[8].eq(i << 3)


class PhasedAccu(Module):
    """Phase accumulator with multiple phased outputs.

    Output data (across cycles and outputs) is such
    that there is always one frequency word offset between successive
    phase samples.

    * Input frequency, phase offset, clear
    * Output `n` phase samples per cycle
    """
    def __init__(self, n, fwidth, pwidth):
        self.f = Signal(fwidth)
        self.p = Signal(pwidth)
        self.clr = Signal(reset=1)
        self.z = [Signal(pwidth, reset_less=True)
                  for _ in range(n)]

        self.submodules.mcm = MCM(fwidth, range(n))
        # reset by clr
        qa = Signal(fwidth, reset_less=True)
        qb = Signal(fwidth, reset_less=True)
        clr_d = Signal(reset_less=True)
        self.sync += [
            clr_d.eq(self.clr),
            qa.eq(qa + (self.f << log2_int(n))),
            self.mcm.i.eq(self.f),
            If(self.clr | clr_d,
                qa.eq(0),
            ),
            If(clr_d,
                self.mcm.i.eq(0),
            ),
            qb.eq(qa + (self.p << fwidth - pwidth)),
            [z.eq((qb + oi)[fwidth - pwidth:])
                for oi, z in zip(self.mcm.o, self.z)]
        ]


class PhaseModulator(Module):
    """Complex phase modulator/shifter.

    * Shifts input `i` by phase `z`
    * Output `o`
    """
    def __init__(self, **kwargs):
        self.submodules.cs = CosSinGen(**kwargs)
        self.submodules.mul = ComplexMultiplier(
            awidth=len(self.cs.x), pwidth=len(self.cs.x))
        self.z = self.cs.z  # cs.z + 1 + mul.a
        self.i = self.mul.b  # mul.b
        self.o = self.mul.p
        self.sync += [
            self.mul.a.i.eq(self.cs.x),
            self.mul.a.q.eq(self.cs.y),
        ]
        self.latency = self.cs.latency + 1 + self.mul.latency


class MultiDDS(Accu):
    """Time division multiplexed oscillator.

    Uses one CosSinGen and one (complex-real) multiplier.
    Latencies are unmatched between parameters
    and channels. Overflowing summation.
    """
    def __init__(self, n, fwidth, xwidth, **kwargs):
        self.i = [Record([
            ("f", fwidth), ("p", xwidth), ("a", xwidth - 1), ("clr", 1)])
                  for i in range(n)]
        self.o = Record(complex(xwidth), reset_less=True)
        self.stb = Signal()
        self.valid = Signal()

        self.submodules.mod = PhaseModulator(x=xwidth - 1, **kwargs)
        # accu
        accu = [Signal(fwidth) for _ in range(n)]
        run = Signal()

        i = Signal(max=n)
        self._i = i
        def cycle(offset):
            return i == offset % n

        for ii, ctrl in enumerate(self.i):
            self.sync += [
                If(run & cycle(ii),
                    accu[ii].eq(accu[ii] + ctrl.f),
                    If(ctrl.clr,
                        accu[ii].eq(0)
                    ),
                ),
                If(cycle(ii + 1),
                    self.mod.z.eq(
                        (accu[ii] + (ctrl.p << fwidth - len(ctrl.p))
                         )[fwidth - len(self.mod.z):]),
                ),
                If(cycle(ii + 2 + self.mod.cs.latency),
                    self.mod.i.i.eq(ctrl.a),
                ),
            ]

        # 2: q, z
        latency = self.mod.latency + 2

        self.sync += [
            If(run,
                i.eq(i + 1),
            ),
            If(cycle(n - 1),
                i.eq(0),
                run.eq(0),
            ),
            If(self.stb,
                run.eq(1),
            ),
            If(run,
                self.o.i.eq(Mux(cycle(latency), 0, self.o.i) +
                            self.mod.o.i),
                self.o.q.eq(Mux(cycle(latency), 0, self.o.q) +
                            self.mod.o.q),
            ),
            self.valid.eq(run & cycle(latency - 1)),
        ]



class PhasedDUC(Module):
    """Phased (multi-sample) digital upconverter/frequency shifter.

    * Input phased complex input sample index `j` as `i[j]`
    * Shift by frequency `f`, phase `p` (phase accumulator clear as `clr`).
    * Output phased sample index `j` as `o[j]`.
    """
    def __init__(self, zl=10, **kwargs):
        self.submodules.accu = PhasedAccu(**kwargs)
        self.f, self.p, self.clr = self.accu.f, self.accu.p, self.accu.clr
        self.i = []
        self.o = []
        self.mods = []
        for i in range(len(self.accu.z)):
            if i & 1:
                use_lut = self.mods[i - 1].cs.lut
            else:
                use_lut = None
            mod = PhaseModulator(z=len(self.accu.z[0]), zl=zl,
                    x=15, use_lut=use_lut)
            self.mods.append(mod)
            self.comb += mod.z.eq(self.accu.z[i])
            self.i.append(mod.i)
            self.o.append(mod.o)
        self.submodules += self.mods
