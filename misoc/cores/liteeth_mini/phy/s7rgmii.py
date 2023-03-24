#
# This file is part of LiteEth, backported to MiSoC.
#
# Copyright (c) 2015-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2022-2022 Mikolaj Sowinski <msowinski@technosystem.com.pl>
# SPDX-License-Identifier: BSD-2-Clause

# RGMII PHY for 7-Series Xilinx FPGA

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import *


class LiteEthPHYHWReset(Module):
    def __init__(self, cycles=256):
        self.reset = Signal()

        # # #

        counter      = Signal(max=cycles + 1)
        counter_done = Signal()
        counter_ce   = Signal()
        self.sync += If(counter_ce, counter.eq(counter + 1))
        self.comb += [
            counter_done.eq(counter == cycles),
            counter_ce.eq(~counter_done),
            self.reset.eq(~counter_done)
        ]


class LiteEthPHYRGMIITX(Module):
    def __init__(self, pads):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))

        # # #

        tx_ctl_obuf  = Signal()
        tx_data_obuf = Signal(4)

        self.specials += [
            Instance("ODDR",
                p_DDR_CLK_EDGE = "SAME_EDGE",
                i_C  = ClockSignal("eth_tx"),
                i_CE = 1,
                i_S  = 0,
                i_R  = 0,
                i_D1 = sink.stb,
                i_D2 = sink.stb,
                o_Q  = tx_ctl_obuf,
            ),
            Instance("OBUF",
                i_I = tx_ctl_obuf,
                o_O = pads.tx_ctl,
            ),
        ]
        for i in range(4):
            self.specials += [
                Instance("ODDR",
                    p_DDR_CLK_EDGE = "SAME_EDGE",
                    i_C  = ClockSignal("eth_tx"),
                    i_CE = 1,
                    i_S  = 0,
                    i_R  = 0,
                    i_D1 = sink.data[i],
                    i_D2 = sink.data[4+i],
                    o_Q  = tx_data_obuf[i],
                ),
                Instance("OBUF",
                    i_I = tx_data_obuf[i],
                    o_O = pads.tx_data[i],
                )
            ]
        self.comb += sink.ack.eq(1)


class LiteEthPHYRGMIIRX(Module):
    def __init__(self, pads, rx_delay=2e-9, iodelay_clk_freq=200e6):
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        assert iodelay_clk_freq in [200e6, 300e6, 400e6]
        iodelay_tap_average = 1 / (2*32 * iodelay_clk_freq)
        rx_delay_taps = round(rx_delay / iodelay_tap_average)
        assert rx_delay_taps < 32, "Exceeded ODELAYE2 max value: {} >= 32".format(rx_delay_taps)

        rx_ctl_ibuf    = Signal()
        rx_ctl_idelay  = Signal()
        rx_ctl         = Signal()
        rx_data_ibuf   = Signal(4)
        rx_data_idelay = Signal(4)
        rx_data        = Signal(8)

        self.specials += [
            Instance("IBUF", i_I=pads.rx_ctl, o_O=rx_ctl_ibuf),
            Instance("IDELAYE2",
                p_IDELAY_TYPE  = "FIXED",
                p_IDELAY_VALUE = rx_delay_taps,
                p_REFCLK_FREQUENCY = iodelay_clk_freq/1e6,
                i_C        = 0,
                i_LD       = 0,
                i_CE       = 0,
                i_LDPIPEEN = 0,
                i_INC      = 0,
                i_IDATAIN  = rx_ctl_ibuf,
                o_DATAOUT  = rx_ctl_idelay,
            ),
            Instance("IDDR",
                p_DDR_CLK_EDGE = "SAME_EDGE_PIPELINED",
                i_C  = ClockSignal("eth_rx"),
                i_CE = 1,
                i_S  = 0,
                i_R  = 0,
                i_D  = rx_ctl_idelay,
                o_Q1 = rx_ctl,
                o_Q2 = Signal(),
            )
        ]
        for i in range(4):
            self.specials += [
                Instance("IBUF",
                    i_I = pads.rx_data[i],
                    o_O = rx_data_ibuf[i],
                ),
                Instance("IDELAYE2",
                    p_IDELAY_TYPE  = "FIXED",
                    p_IDELAY_VALUE = rx_delay_taps,
                    p_REFCLK_FREQUENCY = iodelay_clk_freq/1e6,
                    i_C        = 0,
                    i_LD       = 0,
                    i_CE       = 0,
                    i_LDPIPEEN = 0,
                    i_INC      = 0,
                    i_IDATAIN  = rx_data_ibuf[i],
                    o_DATAOUT  = rx_data_idelay[i],
                ),
                Instance("IDDR",
                    p_DDR_CLK_EDGE = "SAME_EDGE_PIPELINED",
                    i_C  = ClockSignal("eth_rx"),
                    i_CE = 1,
                    i_S  = 0,
                    i_R  = 0,
                    i_D  = rx_data_idelay[i],
                    o_Q1 = rx_data[i],
                    o_Q2 = rx_data[i+4],
                )
            ]

        rx_ctl_d = Signal()
        self.sync += rx_ctl_d.eq(rx_ctl)

        last = Signal()
        self.comb += last.eq(~rx_ctl & rx_ctl_d)
        self.sync += [
            source.stb.eq(rx_ctl),
            source.data.eq(rx_data)
        ]
        self.comb += source.eop.eq(last)


class LiteEthPHYRGMIICRG(Module, AutoCSR):
    def __init__(self, clock_pads, pads, with_hw_init_reset, tx_delay=2e-9, hw_reset_cycles=256):
        self._reset = CSRStorage()

        # # #

        # RX clock
        self.clock_domains.cd_eth_rx = ClockDomain()
        eth_rx_clk_ibuf = Signal()
        self.specials += [
            Instance("IBUF",
                i_I = clock_pads.rx,
                o_O = eth_rx_clk_ibuf,
            ),
            Instance("BUFG",
                i_I = eth_rx_clk_ibuf,
                o_O = self.cd_eth_rx.clk,
            ),
        ]

        # TX clock
        self.clock_domains.cd_eth_tx         = ClockDomain()
        self.clock_domains.cd_eth_tx_delayed = ClockDomain(reset_less=True)
        tx_phase = 125e6*tx_delay*360
        assert tx_phase < 360
        pll_fb = Signal()
        eth_tx_clk = Signal()
        eth_tx_delayed_clk = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                     p_STARTUP_WAIT="FALSE", o_LOCKED=Signal(),

                     # VCO @ 1GHz
                     p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=5.0,
                     p_CLKFBOUT_MULT=8, p_DIVCLK_DIVIDE=1,
                     i_CLKIN1=ClockSignal("eth_rx"), i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                     # 125MHz
                     p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=eth_tx_clk,

                     # 500MHz
                     p_CLKOUT1_DIVIDE=8, p_CLKOUT1_PHASE=tx_phase, o_CLKOUT1=eth_tx_delayed_clk,

                     p_CLKOUT2_DIVIDE=5, p_CLKOUT2_PHASE=0.0, #o_CLKOUT2=,
                     p_CLKOUT3_DIVIDE=5, p_CLKOUT3_PHASE=0.0, #o_CLKOUT3=,
                     p_CLKOUT4_DIVIDE=5, p_CLKOUT4_PHASE=0.0, #o_CLKOUT4=
            ),
            Instance("BUFG", i_I=eth_tx_clk, o_O=self.cd_eth_tx.clk),
            Instance("BUFG", i_I=eth_tx_delayed_clk, o_O=self.cd_eth_tx_delayed.clk),
        ]

        eth_tx_clk_obuf = Signal()
        self.specials += [
            Instance("ODDR",
                p_DDR_CLK_EDGE = "SAME_EDGE",
                i_C  = ClockSignal("eth_tx_delayed"),
                i_CE = 1,
                i_S  = 0,
                i_R  = 0,
                i_D1 = 1,
                i_D2 = 0,
                o_Q  = eth_tx_clk_obuf,
            ),
            Instance("OBUF",
                i_I = eth_tx_clk_obuf,
                o_O = clock_pads.tx,
            )
        ]

        # Reset
        self.reset = reset = Signal()
        if with_hw_init_reset:
            self.submodules.hw_reset = LiteEthPHYHWReset(cycles=hw_reset_cycles)
            self.comb += reset.eq(self._reset.storage | self.hw_reset.reset)
        else:
            self.comb += reset.eq(self._reset.storage)
        if hasattr(pads, "rst_n"):
            self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]


class LiteEthPHYRGMII(Module, AutoCSR):
    dw          = 8
    tx_clk_freq = 125e6
    rx_clk_freq = 125e6
    def __init__(self, clock_pads, pads, with_hw_init_reset=True, tx_delay=2e-9, rx_delay=2e-9,
            iodelay_clk_freq=200e6, hw_reset_cycles=256):
        self.submodules.crg = LiteEthPHYRGMIICRG(clock_pads, pads, with_hw_init_reset, tx_delay, hw_reset_cycles)
        self.submodules.tx  = ClockDomainsRenamer("eth_tx")(LiteEthPHYRGMIITX(pads))
        self.submodules.rx  = ClockDomainsRenamer("eth_rx")(LiteEthPHYRGMIIRX(pads, rx_delay, iodelay_clk_freq))
        self.sink, self.source = self.tx.sink, self.rx.source
