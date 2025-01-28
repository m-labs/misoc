from migen import *

from misoc.cores.coaxpress.common import char_layout
from misoc.cores.code_8b10b import SingleEncoder
from misoc.interconnect.csr import *
from misoc.interconnect.stream import Endpoint

from math import ceil

class HostTXPHYs(Module, AutoCSR):
    """
    A lowspeed multilane TX phys that support reconfigurable linerate with 8b10b encoding
    Supported linerate: 20.83, 41.6 Mbps 
    """
    def __init__(self, pads, sys_clk_freq):
        self.clk_reset = CSR()
        self.bitrate2x_enable = CSRStorage()
        self.enable = CSRStorage()

        # # #

        self.phys = []
        for i, pad in enumerate(pads):
            tx = Transmitter(pad, sys_clk_freq)
            self.phys.append(tx)
            setattr(self.submodules, "tx"+str(i), tx)
            # Connect multi TX phys together
            self.sync += [
                tx.clk_reset.eq(self.clk_reset.re),
                tx.bitrate2x_enable.eq(self.bitrate2x_enable.storage),
                tx.enable.eq(self.enable.storage),
            ]

class Transmitter(Module, AutoCSR):
    def __init__(self, pad, sys_clk_freq):
        self.bitrate2x_enable = Signal()
        self.clk_reset = Signal()
        self.enable = Signal()

        # # #

        self.sink = Endpoint(char_layout)

        self.submodules.cg = cg = ClockGen(sys_clk_freq)
        self.submodules.encoder = encoder = SingleEncoder(True)

        oe = Signal()
        self.sync += [
            If(self.enable,
                self.sink.ack.eq(0),
                If(cg.clk,
                    oe.eq(1),
                    encoder.disp_in.eq(encoder.disp_out),
                    self.sink.ack.eq(1),
                    encoder.d.eq(self.sink.data),
                    encoder.k.eq(self.sink.k),
                )
            ).Else(
                # discard packets until tx is enabled
                self.sink.ack.eq(1),
                oe.eq(0),
            )
        ]

        self.submodules.serializer = serializer = Serializer_10bits(pad)

        self.comb += [
            cg.reset.eq(self.clk_reset),
            cg.freq2x_enable.eq(self.bitrate2x_enable),

            serializer.reset.eq(self.clk_reset),
            serializer.ce.eq(cg.clk_10x),
            serializer.d.eq(encoder.output),
            serializer.oe.eq(oe),
        ]

@ResetInserter()
class ClockGen(Module):
    def __init__(self, sys_clk_freq):
        self.clk = Signal()
        self.clk_10x = Signal() # 48ns (20.83MHz) or 24ns (41.66MHz)

        self.freq2x_enable = Signal()
        # # #

        period = 1e9/sys_clk_freq
        max_count = ceil(48/period)
        counter = Signal(max=max_count, reset=max_count-1)

        clk_div = Signal(max=10, reset=9)

        self.sync += [
            self.clk.eq(0),
            self.clk_10x.eq(0),

            If(counter == 0,
                self.clk_10x.eq(1),
                If(self.freq2x_enable,
                    counter.eq(int(max_count/2)-1),
                ).Else(
                    counter.eq(counter.reset),
                ),
            ).Else(
                counter.eq(counter-1),
            ),

            If(counter == 0,
                If(clk_div == 0,
                    self.clk.eq(1),
                    clk_div.eq(clk_div.reset),
                ).Else(
                    clk_div.eq(clk_div-1),
                )
            )

        ]

@ResetInserter()
@CEInserter()
class Serializer_10bits(Module):
    def __init__(self, pad):
        self.oe = Signal()
        self.d = Signal(10)

        # # #

        tx_bitcount = Signal(max=10)
        tx_reg = Signal(10)

        self.sync += [
            If(self.oe,
                # send LSB first
                pad.eq(tx_reg[0]),
                tx_reg.eq(Cat(tx_reg[1:], 0)),
                tx_bitcount.eq(tx_bitcount + 1),   

                If(tx_bitcount == 9,
                    tx_bitcount.eq(0),
                    tx_reg.eq(self.d),
                ),
            ).Else(
                pad.eq(0),
                tx_bitcount.eq(0),
            )
        ]
