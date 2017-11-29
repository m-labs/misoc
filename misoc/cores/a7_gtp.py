from collections import namedtuple

from migen import *


__all__ = ["QPLLSettings", "QPLLChannel", "QPLL"]


QPLLSettings = namedtuple("QPLLSettings", "refclksel fbdiv fbdiv_45 refclk_div")


class QPLLChannel:
    def __init__(self):
        self.reset = Signal()
        self.lock = Signal()
        self.clk = Signal()
        self.refclk = Signal()


class QPLL(Module):
    def __init__(self, gtrefclk0, qpllsettings0, gtrefclk1=0, qpllsettings1=None):
        self.channels = []

        channel_settings = dict()
        for i, qpllsettings in enumerate((qpllsettings0, qpllsettings1)):
            def add_setting(k, v):
                channel_settings[k.replace("PLLX", "PLL"+str(i))] = v

            if qpllsettings is None:
                add_setting("i_PLLXPD", 1)
            else:
                channel = QPLLChannel()
                self.channels.append(channel)
                add_setting("i_PLLXPD", 0)
                add_setting("i_PLLXLOCKEN", 1)
                add_setting("i_PLLXREFCLKSEL", qpllsettings.refclksel)
                add_setting("p_PLLX_FBDIV", qpllsettings.n2)
                add_setting("p_PLLX_FBDIV_45", qpllsettings.n1)
                add_setting("p_PLLX_REFCLK_DIV", qpllsettings.m)
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
