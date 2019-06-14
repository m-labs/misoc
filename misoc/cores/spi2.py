from migen import *
from migen.genlib.fsm import FSM, NextState
from misoc.interconnect.csr import *
from misoc.interconnect.stream import *
from misoc.interconnect import wishbone


class ClockGen(Module):
    def __init__(self, width):
        # Cycle duration - 1
        self.div = Signal(width)
        # If `extend` is asserted, the next half cycle is
        # extended by the LSB of `div`
        self.extend = Signal()
        # Half cycle done
        self.done = Signal()
        # Continue counting or re-load counter
        self.count = Signal()

        ###

        cnt = Signal(width - 1)
        cnt_done = Signal()
        do_extend = Signal()

        self.comb += [
            cnt_done.eq(cnt == 0),
            self.done.eq(cnt_done & ~do_extend)
        ]
        self.sync += [
            If(self.count,
                If(cnt_done,
                    If(do_extend,
                        do_extend.eq(0)
                    ).Else(
                        cnt.eq(self.div[1:]),
                        do_extend.eq(self.extend & self.div[0])
                    )
                ).Else(
                    cnt.eq(cnt - 1)
                )
            )
        ]


class Register(Module):
    def __init__(self, width):
        # Parallel data out (to serial)
        self.pdo = Signal(width)
        # Parallel data out (from serial)
        self.pdi = Signal(width)
        # Serial data out (from parallel)
        self.sdo = Signal(reset_less=True)
        # Serial data in
        # Must be sampled at a higher layer at self.sample
        self.sdi = Signal()
        # Transmit LSB first
        self.lsb_first = Signal()
        # Load shift register from pdo
        self.load = Signal()
        # Shift SR
        self.shift = Signal()
        # Not used here. Use in Interface to sample into sdo.
        self.sample = Signal()

        ###

        sr = Signal(width, reset_less=True)

        self.comb += [
            self.pdi.eq(Mux(self.lsb_first,
                Cat(sr[1:], self.sdi),
                Cat(self.sdi, sr[:-1])))
        ]
        self.sync += [
            If(self.shift,
                sr.eq(self.pdi),
                self.sdo.eq(Mux(self.lsb_first, self.pdi[0], self.pdi[-1]))
            ),
            If(self.load,
                sr.eq(self.pdo),
                self.sdo.eq(Mux(self.lsb_first, self.pdo[0], self.pdo[-1]))
            )
        ]


class SPIMachine(Module):
    def __init__(self, data_width=32, div_width=8):
        # Number of bits to transfer - 1
        self.length = Signal(max=data_width)
        # Freescale CPHA
        self.clk_phase = Signal()

        # Combinatorial cs and clk signals to be registered
        # in Interface on ce
        self.clk_next = Signal()
        self.cs_next = Signal()
        self.ce = Signal()

        # No transfer is in progress
        self.idle = Signal()
        # When asserted and writiable, load register and start transfer
        self.load = Signal()
        # reg.pdi valid and all bits transferred
        # Asserted at the end of the last hold interval.
        # For one cycle (if the transfer completes the transaction) or
        # until load is asserted.
        self.readable = Signal()
        # Asserted before a transfer until the data has been loaded
        self.writable = Signal()
        # When asserted during load end the transaction with
        # this transfer.
        self.end = Signal()

        self.submodules.reg = reg = Register(data_width)
        self.submodules.cg = cg = ClockGen(div_width)

        ###

        # Bit counter
        n = Signal.like(self.length, reset_less=True)
        # Capture end for the in-flight transfer
        end = Signal(reset_less=True)

        self.comb += [
                self.ce.eq(cg.done & cg.count)
        ]
        self.sync += [
                If(reg.load,
                    n.eq(self.length),
                    end.eq(self.end)
                ),
                If(reg.shift,
                    n.eq(n - 1)
                )
        ]

        fsm = FSM("IDLE")
        self.submodules += fsm

        fsm.act("IDLE",
                self.idle.eq(1),
                self.writable.eq(1),
                self.cs_next.eq(1),
                If(self.load,
                    cg.count.eq(1),
                    reg.load.eq(1),
                    If(self.clk_phase,
                        NextState("PRE"),
                    ).Else(
                        cg.extend.eq(1),
                        NextState("SETUP"),
                    )
                )
        )
        fsm.act("PRE",
                # dummy half cycle after asserting CS in CPHA=1
                self.cs_next.eq(1),
                cg.count.eq(1),
                cg.extend.eq(1),
                self.clk_next.eq(1),
                If(cg.done,
                    NextState("SETUP")
                )
        )
        fsm.act("SETUP",
                self.cs_next.eq(1),
                cg.count.eq(1),
                self.clk_next.eq(~self.clk_phase),
                If(cg.done,
                    reg.sample.eq(1),
                    NextState("HOLD")
                )
        )
        fsm.act("HOLD",
                self.cs_next.eq(1),
                cg.count.eq(1),
                cg.extend.eq(1),
                self.clk_next.eq(self.clk_phase),
                If(cg.done,
                    If(n == 0,
                        self.readable.eq(1),
                        self.writable.eq(1),
                        If(end,
                            self.clk_next.eq(0),
                            self.writable.eq(0),
                            If(self.clk_phase,
                                self.cs_next.eq(0),
                                NextState("WAIT")
                            ).Else(
                                NextState("POST")
                            )
                        ).Elif(self.load,
                            reg.load.eq(1),
                            NextState("SETUP")
                        ).Else(
                            cg.count.eq(0)
                        )
                    ).Else(
                        reg.shift.eq(1),
                        NextState("SETUP")
                    )
                )
        )
        fsm.act("POST",
                # dummy half cycle before deasserting CS in CPHA=0
                cg.count.eq(1),
                If(cg.done,
                    NextState("WAIT")
                )
        )
        fsm.act("WAIT",
                # dummy half cycle to meet CS deassertion minimum timing
                If(cg.done,
                    NextState("IDLE")
                ).Else(
                    cg.count.eq(1)
                )
        )


class SPIInterface(Module):
    """Drive one or more SPI buses with a single interface."""
    def __init__(self, *pads):
        self.cs = Signal(sum(len(p.cs_n) for p in pads))
        self.cs_polarity = Signal.like(self.cs)
        self.clk_next = Signal()
        self.clk_polarity = Signal()
        self.cs_next = Signal()
        self.ce = Signal()
        self.sample = Signal()
        self.offline = Signal()
        self.half_duplex = Signal()
        self.sdi = Signal()
        self.sdo = Signal()

        i = 0
        for p in pads:
            n = len(p.cs_n)
            cs = TSTriple(n)
            cs.o.reset = C((1 << n) - 1)
            clk = TSTriple()
            mosi = TSTriple()
            miso = TSTriple()
            miso_reg = Signal(reset_less=True)
            mosi_reg = Signal(reset_less=True)
            self.specials += [
                    cs.get_tristate(p.cs_n),
                    clk.get_tristate(p.clk),
            ]
            if hasattr(p, "mosi"):
                self.specials += mosi.get_tristate(p.mosi)
            if hasattr(p, "miso"):
                self.specials += miso.get_tristate(p.miso)
            self.comb += [
                    miso.oe.eq(0),
                    mosi.o.eq(self.sdo),
                    miso.o.eq(self.sdo),
                    cs.oe.eq(~self.offline),
                    clk.oe.eq(~self.offline),
                    mosi.oe.eq(~(self.offline | self.half_duplex)),
                    If(self.cs[i:i + n] != 0,
                        self.sdi.eq(Mux(self.half_duplex, mosi_reg, miso_reg))
                    )
            ]
            self.sync += [
                    If(self.ce,
                        cs.o.eq((Replicate(self.cs_next, n)
                            & self.cs[i:i + n]) ^ ~self.cs_polarity[i:i + n]),
                        clk.o.eq(self.clk_next ^ self.clk_polarity)
                    ),
                    If(self.sample,
                        miso_reg.eq(miso.i),
                        mosi_reg.eq(mosi.i)
                    )
            ]
            i += n


class SPIInterfaceXC7Diff(Module):
    def __init__(self, pads, pads_n):
        self.cs = Signal(len(getattr(pads, "cs_n", [0])))
        self.cs_polarity = Signal.like(self.cs)
        self.clk_next = Signal()
        self.clk_polarity = Signal()
        self.cs_next = Signal()
        self.ce = Signal()
        self.sample = Signal()
        self.offline = Signal()
        self.half_duplex = Signal()
        self.sdi = Signal()
        self.sdo = Signal()

        cs = Signal.like(self.cs)
        cs.reset = C((1 << len(self.cs)) - 1)
        clk = Signal()
        miso = Signal()
        mosi = Signal()
        miso_reg = Signal(reset_less=True)
        mosi_reg = Signal(reset_less=True)
        self.comb += [
                self.sdi.eq(Mux(self.half_duplex, mosi_reg, miso_reg))
        ]
        self.sync += [
                If(self.ce,
                    cs.eq((Replicate(self.cs_next, len(self.cs))
                        & self.cs) ^ ~self.cs_polarity),
                    clk.eq(self.clk_next ^ self.clk_polarity)
                ),
                If(self.sample,
                    miso_reg.eq(miso),
                    mosi_reg.eq(mosi)
                )
        ]

        if hasattr(pads, "cs_n"):
            for i in range(len(pads.cs_n)):
                self.specials += Instance("OBUFTDS",
                    i_I=cs[i], i_T=self.offline,
                    o_O=pads.cs_n[i], o_OB=pads_n.cs_n[i])
        self.specials += Instance("OBUFTDS",
            i_I=clk, i_T=self.offline,
            o_O=pads.clk, o_OB=pads_n.clk)
        if hasattr(pads, "mosi"):
            self.specials += Instance("IOBUFDS",
                o_O=mosi, i_I=self.sdo, i_T=self.offline | self.half_duplex,
                io_IO=pads.mosi, io_IOB=pads_n.mosi)
        if hasattr(pads, "miso"):
            self.specials += Instance("IOBUFDS",
                o_O=miso, i_I=self.sdo, i_T=1,
                io_IO=pads.miso, io_IOB=pads_n.miso)


class SPIInterfaceiCE40Diff(Module):
    """
    4-wire differential SPI interface for Lattice iCE40 platforms.

    3-wire SPI (half-duplex) is not supported.

    When using a `miso` signal, make sure to not request the complementary side
    of the differential pair to not confuse yosys/nextpnr (pass `None` or
    nothing for `pads_n.miso`).
    """
    def __init__(self, pads, pads_n):
        self.cs = Signal(len(getattr(pads, "cs_n", [0])))
        self.cs_polarity = Signal.like(self.cs)
        self.clk_next = Signal()
        self.clk_polarity = Signal()
        self.cs_next = Signal()
        self.ce = Signal()
        self.sample = Signal()
        self.offline = Signal()
        self.half_duplex = Signal()
        self.sdi = Signal()
        self.sdo = Signal()

        cs = Signal.like(self.cs)
        cs.reset = C((1 << len(self.cs)) - 1)
        clk = Signal()
        miso = Signal()
        mosi = Signal()
        miso_reg = Signal(reset_less=True)
        mosi_reg = Signal(reset_less=True)
        self.comb += [
            self.sdi.eq(miso_reg)
        ]

        self.sync += [If(self.ce,
                         cs.eq((Replicate(self.cs_next, len(self.cs))
                                & self.cs) ^ ~self.cs_polarity),
                        clk.eq(self.clk_next ^ self.clk_polarity)),
                      If(self.sample,
                         miso_reg.eq(miso),
                         mosi_reg.eq(mosi)),
        ]

        # CS_N
        if hasattr(pads, "cs_n"):
            for i in range(len(pads.cs_n)):
                self.specials += Instance("SB_IO",
                                          p_PIN_TYPE=C(0b101000, 6),
                                          p_IO_STANDARD="SB_LVCMOS",
                                          io_PACKAGE_PIN=pads.cs_n[i],
                                          i_OUTPUT_ENABLE=~self.offline,
                                          i_D_OUT_0=cs[i])
                self.specials += Instance("SB_IO",
                                          p_PIN_TYPE=C(0b101000, 6),
                                          p_IO_STANDARD="SB_LVCMOS",
                                          io_PACKAGE_PIN=pads_n.cs_n[i],
                                          i_OUTPUT_ENABLE=~self.offline,
                                          i_D_OUT_0=~cs[i])

        # CLK
        self.specials += Instance("SB_IO",
                                  p_PIN_TYPE=C(0b101000, 6),
                                  p_IO_STANDARD="SB_LVCMOS",
                                  io_PACKAGE_PIN=pads.clk,
                                  i_OUTPUT_ENABLE=~self.offline,
                                  i_D_OUT_0=clk)
        self.specials += Instance("SB_IO",
                                  p_PIN_TYPE=C(0b101000, 6),
                                  p_IO_STANDARD="SB_LVCMOS",
                                  io_PACKAGE_PIN=pads_n.clk,
                                  i_OUTPUT_ENABLE=~self.offline,
                                  i_D_OUT_0=~clk)

        # MOSI
        if hasattr(pads, "mosi"):
            self.specials += Instance("SB_IO",
                                      p_PIN_TYPE=C(0b101001, 6),
                                      p_IO_STANDARD="SB_LVCMOS",
                                      io_PACKAGE_PIN=pads.mosi,
                                      i_OUTPUT_ENABLE=~self.offline,
                                      i_D_OUT_0=self.sdo,
                                      o_D_IN_0=mosi)
            self.specials += Instance("SB_IO",
                                      p_PIN_TYPE=C(0b101001, 6),
                                      p_IO_STANDARD="SB_LVCMOS",
                                      io_PACKAGE_PIN=pads_n.mosi,
                                      i_OUTPUT_ENABLE=~self.offline,
                                      i_D_OUT_0=~self.sdo)

        # MISO
        if hasattr(pads, "miso"):
            # make sure pads_n.miso is not requested
            # to not confuse yosys/nextpnr
            assert getattr(pads_n, "miso", None) is None
            self.specials += Instance("SB_IO",
                                      p_PIN_TYPE=C(0b000001, 6),
                                      p_IO_STANDARD="SB_LVDS_INPUT",
                                      io_PACKAGE_PIN=pads.miso,
                                      i_D_OUT_0=self.sdo,
                                      o_D_IN_0=miso)


class SPIMaster(Module, AutoCSR):
    """SPI Master.

    Notes:
        * M (= 32) is the data width (width of the data register,
          maximum bits per transfer)
        * Every transfer consists of a 1-M bit read/write.
        * A transaction consists of one or more transfers.
        * The a transfer that starts (loads) with end asserted completes the
          transaction.
        * cs is asserted at the beginning and deasserted at the end of the
          transaction.
        * cs handling is agnostic to whether it is one-hot or decoded
          somewhere downstream. If it is decoded, "cs_n all deasserted"
          should be handled accordingly (no slave selected).
          If it is one-hot, selecting multiple slaves should only be attempted
          if miso is either not connected between slaves, or open collector,
          or correctly multiplexed externally.
        * If cs_polarity == 0 (cs active low, the default),
          "cs all deasserted" means "all cs_n bits high".
        * cs is not mandatory in pads. It can be a dummy signal.
          Framing and chip selection can also
          be handled independently through other means.
        * If there is a miso wire in pads, the input and output can be done
          with two signals (a.k.a. 4-wire SPI), else mosi must be used for
          both output and input (a.k.a. 3-wire SPI) and self.half_duplex
          must to be set when reading data is desired.
        * For 4-wire SPI there is no difference between read and write.
          For 3-wire SPI serial data is read from mosi which is an input.
        * 3-wire SPI with MISO but no MOSI (used by some ADCs) is also supported.
        * The first bit output on mosi is always the MSB/LSB (depending on
          self._lsb_first) of the data register, independent of
          length. The last bit input from miso always ends up in
          the LSB/MSB (respectively) of the data register, independent of
          read_len. Data in data_write needs to be MSB/LSB-aligned. Data in
          data_read is MSB/LSB aligned.
        * Writes to the config register take effect immediately.
          The data CSR is updated at the end of a transfer.
          Writes to the data CSR are used to load data and start a transfer.

    Transaction Sequence:
        * Wait for idle.
        * For each transfer:
            * Wait for writable.
            * Change config registers (including end) (optional).
            * Write the data register.
            * Wait for readable (optional).
            * Read the data register (optional).
    """
    def __init__(self, interface, data_width=32, div_width=8):
        self.data = CSRStorage(data_width, atomic_write=True,
                write_from_dev=True)
        self.length = CSRStorage(log2_int(data_width))
        self.cs = CSRStorage(len(interface.cs))
        self.cs_polarity = CSRStorage(len(interface.cs))
        self.div = CSRStorage(div_width)
        self.offline = CSRStorage(reset=1)
        self.clk_polarity = CSRStorage()
        self.clk_phase = CSRStorage()
        self.lsb_first = CSRStorage()
        self.half_duplex = CSRStorage()
        self.end = CSRStorage(reset=1)

        self.readable = CSRStatus()
        self.writable = CSRStatus()
        self.idle = CSRStatus()
        self.data_width = CSRConstant(data_width)
        self.div_width = CSRConstant(div_width)
        self.cs_width = CSRConstant(self.cs.size)

        self.submodules.interface = interface
        self.submodules.spi = spi = SPIMachine(
            data_width=data_width, div_width=div_width)

        ###

        self.comb += [
                spi.reg.pdo.eq(self.data.storage),
                self.data.dat_w.eq(spi.reg.pdi),
                self.data.we.eq(spi.readable),
                spi.length.eq(self.length.storage),
                spi.end.eq(self.end.storage),
                spi.cg.div.eq(self.div.storage),
                spi.load.eq(self.data.re),
                spi.clk_phase.eq(self.clk_phase.storage),
                spi.reg.lsb_first.eq(self.lsb_first.storage),
                self.readable.status.eq(spi.readable),
                self.writable.status.eq(spi.writable),
                self.idle.status.eq(spi.idle),

                interface.half_duplex.eq(self.half_duplex.storage),
                interface.cs.eq(self.cs.storage),
                interface.cs_polarity.eq(self.cs_polarity.storage),
                interface.clk_polarity.eq(self.clk_polarity.storage),
                interface.offline.eq(self.offline.storage),
                interface.cs_next.eq(spi.cs_next),
                interface.clk_next.eq(spi.clk_next),
                interface.ce.eq(spi.ce),
                interface.sample.eq(spi.reg.sample),
                spi.reg.sdi.eq(interface.sdi),
                interface.sdo.eq(spi.reg.sdo)
        ]

    def test(self):
        assert (yield self.data_width.value) == 32
        assert (yield self.div_width.value) == 8
        assert (yield self.cs_width.value) > 0
        assert (yield from self.idle.read())
        yield from self.offline.write(0)
        yield from self.cs.write(1)
        yield from self.cs_polarity.write(0b00)
        yield from self.div.write(3)
        yield from self.clk_polarity.write(0)
        yield from self.clk_phase.write(0)
        yield from self.lsb_first.write(1)
        yield from self.half_duplex.write(0)

        def transfer(data, length, end):
            assert (yield from self.writable.read())
            yield from self.length.write(length)
            yield from self.end.write(end)
            yield from self.data.write(data)
            while not (yield from self.readable.read()):
                yield
            yield
            # FIXME:
            # CSRStorage(write_from_dev=True) broken in sim
            # return (yield from self.data.read())
            return (yield self.data.dat_w)

        w = 0x12345678
        r = yield from transfer(w, 3, 1)
        print(hex(r))
        while not (yield from self.idle.read()):
            yield
        yield

        r = yield from transfer(w, 3, 0)
        r = yield from transfer(w, 3, 1)
        while not (yield from self.idle.read()):
            yield


class _TestTristate(Module):
    def __init__(self, t):
        oe = Signal()
        self.comb += [
            t.target.eq(t.o),
            oe.eq(t.oe),
            t.i.eq(t.o),
        ]


if __name__ == "__main__":
    from migen.fhdl.verilog import convert
    p0 = Record([("cs_n", 2), ("clk", 1), ("mosi", 1), ("miso", 1)])
    iface = SPIInterface(p0)
    dut = SPIMaster(iface, data_width=32, div_width=8)
    # print(convert(dut))

    from migen.fhdl.specials import Tristate
    Tristate.lower = _TestTristate
    # FIXME:
    # CSRStorage(write_from_dev=True) broken in sim
    # dut.submodules += GenericBank(dut.get_csrs(), 8)
    run_simulation(dut, dut.test(), vcd_name="spi_master.vcd")
