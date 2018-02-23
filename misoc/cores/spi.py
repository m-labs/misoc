import collections
from functools import reduce
from operator import or_
import warnings

from migen import *
from migen.genlib.fsm import FSM, NextState
from misoc.interconnect.csr import *


"""
This core is deprecated. The interface is complicated and hard to use
right in the case of chained transactions. Use the new `spi2` core.
"""
warnings.warn("Core `spi` is deprecated. Use `spi2`.", DeprecationWarning)


class SPIClockGen(Module):
    def __init__(self, width):
        # SPI clock cycle duration for the current cycle
        self.load = Signal(width)
        # The LSB of `load` is applied to the SPI clock phase
        # with `clk == bias`
        self.bias = Signal()
        self.edge = Signal()
        self.clk = Signal(reset=1)

        cnt = Signal.like(self.load)
        cnt_done = Signal()
        bias = Signal()
        bias_done = Signal()
        self.comb += [
            cnt_done.eq(cnt == self.load[1:]),
            bias.eq(self.load[0] & (self.clk == self.bias)),
            self.edge.eq(cnt_done & (~bias | bias_done)),
        ]
        self.sync += [
            If(cnt_done,
                bias_done.eq(1),
            ).Else(
                cnt.eq(cnt + 1),
            ),
            If(self.edge,
                cnt.eq(0),
                bias_done.eq(0),
                self.clk.eq(~self.clk),
            )
        ]


class SPIRegister(Module):
    def __init__(self, width):
        self.data = Signal(width)
        self.o = Signal()
        self.i = Signal()
        self.lsb = Signal()
        self.shift = Signal()
        self.sample = Signal()

        self.comb += [
            self.o.eq(Mux(self.lsb, self.data[0], self.data[-1])),
        ]
        self.sync += [
            If(self.lsb,
                If(self.sample,
                    self.data[-1].eq(self.i),
                ),
                If(self.shift,
                    self.data[:-1].eq(self.data[1:]),
                )
            ).Else(
                If(self.sample,
                    self.data[0].eq(self.i),
                ),
                If(self.shift,
                    self.data[1:].eq(self.data[:-1]),
                )
            )
        ]


class SPIBitCounter(Module):
    def __init__(self, width):
        self.n_read = Signal(width)
        self.n_write = Signal(width)
        self.read = Signal()
        self.write = Signal()
        self.done = Signal()

        self.comb += [
            self.write.eq(self.n_write != 0),
            self.read.eq(self.n_read != 0),
            self.done.eq(~(self.write | self.read)),
        ]
        self.sync += [
            If(self.write,
                self.n_write.eq(self.n_write - 1),
            ).Elif(self.read,
                self.n_read.eq(self.n_read - 1),
            )
        ]


class SPIMachine(Module):
    def __init__(self, data_width, clock_width, bits_width):
        ce = CEInserter()
        self.submodules.cg = ce(SPIClockGen(clock_width))
        self.submodules.reg = ce(SPIRegister(data_width))
        self.submodules.bits = ce(SPIBitCounter(bits_width))
        self.div_write = Signal.like(self.cg.load)
        self.div_read = Signal.like(self.cg.load)
        self.clk_phase = Signal()
        self.start = Signal()
        self.cs = Signal()
        self.cs_next = Signal()
        self.oe = Signal()
        self.done = Signal()

        # # #

        fsm = CEInserter()(FSM("IDLE"))
        self.submodules += fsm

        fsm.act("IDLE",
            If(self.start,
                If(self.clk_phase,
                    NextState("WAIT"),
                ).Else(
                    NextState("SETUP"),
                )
            )
        )
        fsm.act("SETUP",
            self.reg.sample.eq(1),
            NextState("HOLD"),
        )
        fsm.act("HOLD",
            If(self.bits.done & ~self.start,
                If(self.clk_phase,
                    NextState("IDLE"),
                ).Else(
                    NextState("WAIT"),
                )
            ).Else(
                self.reg.shift.eq(~self.start),
                NextState("SETUP"),
            )
        )
        fsm.act("WAIT",
            If(self.bits.done,
                NextState("IDLE"),
            ).Else(
                NextState("SETUP"),
            )
        )

        write0 = Signal()
        read0 = Signal()
        self.sync += [
            If(self.cg.edge & self.reg.shift,
                write0.eq(self.bits.write),
                read0.eq(self.bits.read),
            ),
            If(self.cg.edge & fsm.before_entering("IDLE"),
                write0.eq(0),
                read0.eq(0),
            ),
        ]
        self.comb += [
            self.cg.ce.eq(self.start | self.cs | ~self.cg.edge),
            If((read0 | self.bits.read) & ~self.bits.write,
                self.cg.load.eq(self.div_read),
            ).Else(
                self.cg.load.eq(self.div_write),
            ),
            self.cg.bias.eq(self.clk_phase),
            fsm.ce.eq(self.cg.edge),
            self.cs.eq(~fsm.ongoing("IDLE")),
            self.cs_next.eq(fsm.before_leaving("IDLE") |
                (self.cs & ~fsm.before_entering("IDLE"))),
            self.reg.ce.eq(self.cg.edge),
            self.bits.ce.eq(self.cg.edge & self.reg.sample),
            self.done.eq(self.cg.edge & self.bits.done & fsm.ongoing("HOLD")),
            self.oe.eq(write0 | self.bits.write),
        ]


class SPIMaster(Module, AutoCSR):
    """SPI Master.

    *This core is deprecated. The interface is complicated and hard to use
    right in the case of chained transactions. Use the new `spi2` core.*

    Notes:
        * M = 32 is the data width (width of the data register,
          maximum write bits, maximum read bits)
        * Every transfer consists of a write_length 0-M bit write followed
          by a read_length 0-M bit read.
        * cs_n is asserted at the beginning and deasserted at the end of the
          transfer if there is no other transfer pending.
        * cs_n handling is agnostic to whether it is one-hot or decoded
          somewhere downstream. If it is decoded, "cs_n all deasserted"
          should be handled accordingly (no slave selected).
          If it is one-hot, asserting multiple slaves should only be attempted
          if miso is either not connected between slaves, or open collector,
          or correctly multiplexed externally.
        * If self._cs_polarity == 0 (cs active low, the default),
          "cs_n all deasserted" means "all cs_n bits high".
        * cs is not mandatory in pads. Framing and chip selection can also
          be handled independently through other means.
        * If there is a miso wire in pads, the input and output can be done
          with two signals (a.k.a. 4-wire SPI), else mosi must be used for
          both output and input (a.k.a. 3-wire SPI) and self._half_duplex
          must to be set when reading data is desired.
        * For 4-wire SPI only the sum of read_length and write_length matters.
          The behavior is the same no matter how the total transfer length is
          divided between the two. For 3-wire SPI, the direction of mosi/miso
          is switched from output to input after write_len cycles, at the
          "shift_out" clk edge corresponding to bit write_length + 1 of the
          transfer.
        * The first bit output on mosi is always the MSB/LSB (depending on
          self._lsb_first) of the data register, independent of
          xfer.write_len. The last bit input from miso always ends up in
          the LSB/MSB (respectively) of the data register, independent of
          read_len.
        * Data output on mosi in 4-wire SPI during the read cycles is what
          is found in the data register at the time.
          Data in the data register outside the least/most (depending
          on self._lsb_first) significant read_length bits is what is
          seen on miso during the write cycles.
        * The SPI data register is double-buffered: Once a transfer has
          started, new write data can be written, queuing a new transfer.
          Transfers submitted this way are chained and executed without
          deasserting cs. Once a transfer completes, the previous transfer's
          read data is available in the data register.
        * Writes to the config register take effect immediately. Writes to xfer
          and data are synchronized to the start of a transfer.
        * A wishbone data register write is ack-ed when the transfer has
          been written to the intermediate buffer. It will be started when
          there are no other transactions being executed, either starting
          a new SPI transfer of chained to an in-flight transfer.
          Writes take two cycles unless the write is to the data register
          and another chained transfer is pending and the transfer being
          executed is not complete. Reads always finish in two cycles.

    Transaction Sequence:
        * If desired, write the config register to set up the core.
        * If desired, write the xfer register to change lengths and cs_n.
        * Write the data register (also for zero-length writes),
          writing triggers the transfer and when the transfer is accepted to
          the inermediate buffer, the write is ack-ed.
        * If desired, read the data register corresponding to the last
          completed transfer.
        * If desired, change xfer register for the next transfer.
        * If desired, write data queuing the next (possibly chained) transfer.
    """
    def __init__(self, pads, data_width=32, clock_width=8, bits_width=6):
        if isinstance(pads, collections.Iterable):
            pads_list = pads
        else:
            pads_list = [pads]

        # CSR
        self._data_read = CSRStatus(data_width)
        self._data_write = CSRStorage(data_width, atomic_write=True)
        self._xfer_len_read = CSRStorage(bits_width)
        self._xfer_len_write = CSRStorage(bits_width)
        self._cs = CSRStorage(sum(len(pads.cs_n) for pads in pads_list))
        self._offline = CSRStorage(reset=1)
        self._cs_polarity = CSRStorage(len(self._cs.storage))
        self._clk_polarity = CSRStorage()
        self._clk_phase = CSRStorage()
        self._lsb_first = CSRStorage()
        self._half_duplex = CSRStorage()
        self._active = CSRStatus()
        self._pending = CSRStatus()
        self._clk_div_read = CSRStorage(clock_width)
        self._clk_div_write = CSRStorage(clock_width)
        self.data_width = CSRConstant(data_width)
        self.clock_width = CSRConstant(clock_width)
        self.bits_width = CSRConstant(bits_width)
        self.cs_width = CSRConstant(len(self._cs.storage))

        self.submodules.spi = spi = SPIMachine(
            data_width=data_width + 1,
            clock_width=clock_width,
            bits_width=bits_width)

        pending = Signal(1)
        cs = Signal.like(self._cs.storage)

        ###

        self.comb += [
            spi.start.eq(pending & (~spi.cs | spi.done)),
            spi.clk_phase.eq(self._clk_phase.storage),
            spi.reg.lsb.eq(self._lsb_first.storage),
            spi.div_write.eq(self._clk_div_write.storage),
            spi.div_read.eq(self._clk_div_read.storage),
            self._pending.status.eq(pending),
            self._active.status.eq(spi.cs),
        ]
        self.sync += [
            If(spi.done,
                self._data_read.status.eq(
                    Mux(spi.reg.lsb, spi.reg.data[1:], spi.reg.data[:-1])),
            ),
            If(spi.start,
                cs.eq(self._cs.storage),
                spi.bits.n_write.eq(self._xfer_len_write.storage),
                spi.bits.n_read.eq(self._xfer_len_read.storage),
                If(spi.reg.lsb,
                    spi.reg.data[:-1].eq(self._data_write.storage),
                ).Else(
                    spi.reg.data[1:].eq(self._data_write.storage),
                ),
                pending.eq(0),
            ),

            # CSR bus will honor all reads and writes. A write to the
            # data_write register when pending is active will overwrite
            # the existing data. A user must query the pending status
            # register before writing.

            If(self._data_write.re == 1,
                pending.eq(1),
            ),
        ]

        # I/O
        all_cs = Signal(len(cs))
        self.comb += all_cs.eq((cs & Replicate(spi.cs, len(cs))) ^
                ~self._cs_polarity.storage)
        offset = 0
        for pads in pads_list:
            cs_n_t = TSTriple(len(pads.cs_n))
            self.specials += cs_n_t.get_tristate(pads.cs_n)
            self.comb += [
                cs_n_t.oe.eq(~self._offline.storage),
                cs_n_t.o.eq(all_cs[offset:]),
            ]
            offset += len(pads.cs_n)

        offset = 0
        miso_r = Signal(len(cs))
        mosi_t_i_r = Signal(len(cs))
        for pads in pads_list:
            clk_t = TSTriple()
            self.specials += clk_t.get_tristate(pads.clk)
            self.comb += [
                clk_t.oe.eq(~self._offline.storage),
            ]
            self.sync += [
                If(spi.cg.ce & spi.cg.edge,
                    clk_t.o.eq((~spi.cg.clk & spi.cs_next) ^
                        self._clk_polarity.storage),
                )
            ]

            mosi_t = TSTriple()
            self.specials += mosi_t.get_tristate(pads.mosi)
            self.comb += [
                mosi_t.oe.eq(~self._offline.storage & spi.cs &
                            (spi.oe | ~self._half_duplex.storage)),
                mosi_t.o.eq(spi.reg.o),
            ]
            for i in range(len(pads.cs_n)):
                self.comb += miso_r[offset].eq(getattr(pads, "miso", 0))
                self.comb += mosi_t_i_r[offset].eq(mosi_t.i)
                offset += 1

        self.comb += spi.reg.i.eq((Mux(self._half_duplex.storage, mosi_t_i_r, miso_r) & cs) != 0)
