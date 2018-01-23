from collections import namedtuple
from math import ceil

from migen import *
from migen.genlib.cdc import MultiReg, PulseSynchronizer
from migen.genlib.fsm import FSM

__all__ = ["QPLLSettings", "QPLLChannel", "QPLL", "GTPTxInit", "GTPRxInit"]


QPLLSettings = namedtuple("QPLLSettings", "refclksel fbdiv fbdiv_45 refclk_div")


class QPLLChannel:
    def __init__(self, index):
        self.index = index
        self.reset = Signal()
        self.lock = Signal()
        self.clk = Signal()
        self.refclk = Signal()


class QPLL(Module):
    def __init__(self, gtrefclk0, qpllsettings0, gtrefclk1=0, qpllsettings1=None):
        self.channels = []

        channel_settings = dict()
        for i, qpllsettings in enumerate((qpllsettings0, qpllsettings1)):
            channel = QPLLChannel(i)
            self.channels.append(channel)

            def add_setting(k, v):
                channel_settings[k.replace("PLLX", "PLL"+str(i))] = v

            if qpllsettings is None:
                add_setting("i_PLLXPD", 1)
            else:
                add_setting("i_PLLXPD", 0)
                add_setting("i_PLLXLOCKEN", 1)
                add_setting("i_PLLXREFCLKSEL", qpllsettings.refclksel)
                add_setting("p_PLLX_FBDIV", qpllsettings.fbdiv)
                add_setting("p_PLLX_FBDIV_45", qpllsettings.fbdiv_45)
                add_setting("p_PLLX_REFCLK_DIV", qpllsettings.refclk_div)
                add_setting("i_PLLXRESET", channel.reset)
                add_setting("o_PLLXLOCK", channel.lock)
                add_setting("o_PLLXOUTCLK", channel.clk)
                add_setting("o_PLLXOUTREFCLK", channel.refclk)

        self.specials += \
            Instance("GTPE2_COMMON",
                i_GTREFCLK0=gtrefclk0,
                i_GTREFCLK1=gtrefclk1,
                i_BGBYPASSB=1,
                i_BGMONITORENB=1,
                i_BGPDB=1,
                i_BGRCALOVRD=0b11111,
                i_RCALENB=1,
                **channel_settings
            )


class GTPTxInit(Module):
    def __init__(self, sys_clk_freq):
        self.qpll_reset = Signal()
        self.qpll_lock = Signal()
        self.tx_reset = Signal()
        self.done = Signal()

        # Handle async signals
        qpll_reset = Signal()
        tx_reset = Signal()
        self.sync += [
            self.qpll_reset.eq(qpll_reset),
            self.tx_reset.eq(tx_reset)
        ]
        self.qpll_reset.attr.add("no_retiming")
        self.tx_reset.attr.add("no_retiming")
        qpll_lock = Signal()
        self.specials += MultiReg(self.qpll_lock, qpll_lock)

        # After configuration, transceiver resets have to stay low for
        # at least 500ns.
        # See https://www.xilinx.com/support/answers/43482.html
        timer_max = ceil(500e-9*sys_clk_freq)
        timer = Signal(max=timer_max+1)
        tick = Signal()
        self.sync += [
            tick.eq(0),
            If(timer == timer_max,
                tick.eq(1),
                timer.eq(0)
            ).Else(
                timer.eq(timer + 1)
            )
        ]

        fsm = FSM()
        self.submodules += fsm

        fsm.act("WAIT",
            If(tick, NextState("QPLL_RESET"))
        )
        fsm.act("QPLL_RESET",
            tx_reset.eq(1),
            qpll_reset.eq(1),
            If(tick, NextState("WAIT_QPLL_LOCK"))
        )
        fsm.act("WAIT_QPLL_LOCK",
            tx_reset.eq(1),
            If(qpll_lock & tick, NextState("DONE"))
        )
        fsm.act("DONE",
            self.done.eq(1)
        )


# As usual, Xilinx did not miss the opportunity to mess that up.
# See: https://www.xilinx.com/support/answers/53561.html
class GTPRxInit(Module):
    def __init__(self, sys_clk_freq):
        self.rx_reset = Signal()
        self.rx_pma_reset_done = Signal()

        # DRPCLK must be driven by the system clock
        self.drpaddr = Signal(9)
        self.drpen = Signal()
        self.drpdi = Signal(16)
        self.drprdy = Signal()
        self.drpdo = Signal(16)
        self.drpwe = Signal()

        self.enable = Signal()
        self.restart = Signal()
        self.done = Signal()

        # Handle async signals
        rx_reset = Signal()
        self.sync += self.rx_reset.eq(rx_reset)
        self.rx_reset.attr.add("no_retiming")
        rx_pma_reset_done = Signal()
        self.specials += MultiReg(self.rx_pma_reset_done, rx_pma_reset_done)

        drpvalue = Signal(16)
        drpmask = Signal()
        self.comb += [
            self.drpaddr.eq(0x011),
            If(drpmask,
                self.drpdi.eq(drpvalue & 0xf7ff)
            ).Else(
                self.drpdi.eq(drpvalue)
            )
        ]

        rx_pma_reset_done_r = Signal()
        self.sync += rx_pma_reset_done_r.eq(rx_pma_reset_done)

        fsm = FSM()
        self.submodules += fsm

        fsm.act("WAIT_ENABLE",
            If(self.enable, NextState("GTRXRESET"))
        )
        fsm.act("GTRXRESET",
            rx_reset.eq(1),
            NextState("DRP_READ_ISSUE")
        )
        fsm.act("DRP_READ_ISSUE",
            rx_reset.eq(1),
            self.drpen.eq(1),
            NextState("DRP_READ_WAIT")
        )
        fsm.act("DRP_READ_WAIT",
            rx_reset.eq(1),
            If(self.drprdy,
                NextValue(drpvalue, self.drpdo),
                NextState("DRP_MOD_ISSUE")
            )
        )
        fsm.act("DRP_MOD_ISSUE",
            rx_reset.eq(1),
            drpmask.eq(1),
            self.drpen.eq(1),
            self.drpwe.eq(1),
            NextState("DRP_MOD_WAIT")
        )
        fsm.act("DRP_MOD_WAIT",
            rx_reset.eq(1),
            If(self.drprdy,
                NextState("WAIT_PMARST_FALL")
            )
        )
        fsm.act("WAIT_PMARST_FALL",
            If(rx_pma_reset_done_r & ~rx_pma_reset_done,
                NextState("DRP_RESTORE_ISSUE")
            )
        )
        fsm.act("DRP_RESTORE_ISSUE",
            self.drpen.eq(1),
            self.drpwe.eq(1),
            NextState("DRP_RESTORE_WAIT")
        )
        fsm.act("DRP_RESTORE_WAIT",
            If(self.drprdy,
                NextState("DONE")
            )
        )
        fsm.act("DONE",
            self.done.eq(1),
            If(self.restart, NextState("WAIT_ENABLE"))
        )
