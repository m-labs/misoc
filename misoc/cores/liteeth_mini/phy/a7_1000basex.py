from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.cores.a7_gtp import *
from misoc.cores.liteeth_mini.phy.pcs_1000basex import *


class Gearbox(Module):
    def __init__(self):
        self.tx_data = Signal(10)
        self.tx_data_half = Signal(20)
        self.rx_data_half = Signal(20)
        self.rx_data = Signal(10)

        # TX
        buf = Signal(20)
        self.sync.eth_tx += buf.eq(Cat(buf[10:], self.tx_data))
        self.sync.eth_tx_half += self.tx_data_half.eq(buf)

        # RX
        phase_half = Signal()
        phase_half_rereg = Signal()
        self.sync.eth_rx_half += phase_half_rereg.eq(phase_half)
        self.sync.eth_rx += [
            If(phase_half == phase_half_rereg,
                self.rx_data.eq(self.rx_data_half[10:])
            ).Else(
                self.rx_data.eq(self.rx_data_half[:10])
            ),
            phase_half.eq(~phase_half),
        ]


class A7_1000BASEX(Module):
    def __init__(self, qpll_channel, data_pads, sys_clk_freq, internal_loopback=False):
        pcs = PCS(lsb_first=True)
        self.submodules += pcs

        self.dw = 8
        self.sink = pcs.sink
        self.source = pcs.source

        self.clock_domains.cd_eth_tx = ClockDomain()
        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx_half = ClockDomain(reset_less=True)
        self.clock_domains.cd_eth_rx_half = ClockDomain(reset_less=True)

        # for specifying clock constraints. 62.5MHz clocks.
        self.txoutclk = Signal()
        self.rxoutclk = Signal()

        # # #

        # GTP transceiver
        tx_reset = Signal()
        tx_mmcm_locked = Signal()
        tx_data = Signal(20)

        rx_reset = Signal()
        rx_mmcm_locked = Signal()
        rx_data = Signal(20)
        rx_pma_reset_done = Signal()

        drpaddr = Signal(8)
        drpen = Signal()
        drpdi = Signal(16)
        drprdy = Signal()
        drpdo = Signal(16)
        drpwe = Signal()

        self.specials += \
            Instance("GTPE2_CHANNEL",
                i_GTRESETSEL=0,
                i_RESETOVRD=0,
                p_SIM_RESET_SPEEDUP="FALSE",

                # PMA Attributes
                p_PMA_RSV=0x333,
                p_PMA_RSV2=0x2040,
                p_PMA_RSV3=0,
                p_PMA_RSV4=0,
                p_RX_BIAS_CFG=0b0000111100110011,
                p_RX_CM_SEL=0b01,
                p_RX_CM_TRIM=0b1010,
                p_RX_OS_CFG=0b10000000,
                p_RXLPM_IPCM_CFG=1,
                i_RXELECIDLEMODE=0b11,
                i_RXOSINTCFG=0b0010,
                i_RXOSINTEN=1,

                # Power-Down Attributes
                p_PD_TRANS_TIME_FROM_P2=0x3c,
                p_PD_TRANS_TIME_NONE_P2=0x3c,
                p_PD_TRANS_TIME_TO_P2=0x64,

                # QPLL
                i_PLL0CLK=qpll_channel.clk,
                i_PLL0REFCLK=qpll_channel.refclk,

                # TX clock
                p_TXBUF_EN="TRUE",
                p_TX_XCLK_SEL="TXOUT",
                o_TXOUTCLK=self.txoutclk,
                p_TXOUT_DIV=4,
                i_TXSYSCLKSEL=0b00,
                i_TXOUTCLKSEL=0b11,

                # TX Startup/Reset
                p_TXSYNC_OVRD=1,
                i_TXPHDLYPD=1,
                i_GTTXRESET=tx_reset,
                i_TXUSERRDY=tx_mmcm_locked,

                # TX data
                p_TX_DATA_WIDTH=20,
                i_TXDLYBYPASS=1,
                i_TXCHARDISPMODE=Cat(tx_data[9], tx_data[19]),
                i_TXCHARDISPVAL=Cat(tx_data[8], tx_data[18]),
                i_TXDATA=Cat(tx_data[:8], tx_data[10:18]),
                i_TXUSRCLK=ClockSignal("eth_tx_half"),
                i_TXUSRCLK2=ClockSignal("eth_tx_half"),

                # TX electrical
                i_TXBUFDIFFCTRL=0b100,
                i_TXDIFFCTRL=0b1000,

                # Internal Loopback
                i_LOOPBACK=0b010 if internal_loopback else 0b000,

                # RX Startup/Reset
                i_RXPHDLYPD=1,
                i_GTRXRESET=rx_reset,
                i_RXUSERRDY=rx_mmcm_locked,
                # Xilinx garbage (AR53561)
                o_RXPMARESETDONE=rx_pma_reset_done,
                i_DRPADDR=drpaddr,
                i_DRPEN=drpen,
                i_DRPDI=drpdi,
                o_DRPRDY=drprdy,
                o_DRPDO=drpdo,
                i_DRPWE=drpwe,
                i_DRPCLK=ClockSignal(),

                # RX clock
                p_RX_CLK25_DIV=5,
                p_TX_CLK25_DIV=5,
                p_RX_XCLK_SEL="RXREC",
                p_RXOUT_DIV=4,
                i_RXSYSCLKSEL=0b00,
                i_RXOUTCLKSEL=0b010,
                o_RXOUTCLK=self.rxoutclk,
                i_RXUSRCLK=ClockSignal("eth_rx_half"),
                i_RXUSRCLK2=ClockSignal("eth_rx_half"),
                p_RXCDR_CFG=0x0000107FE106001041010,
                p_RXPI_CFG1=1,
                p_RXPI_CFG2=1,

                # RX Clock Correction Attributes
                p_CLK_CORRECT_USE="FALSE",

                # RX data
                p_RXBUF_EN="TRUE",
                p_RXDLY_CFG=0x001f,
                p_RXDLY_LCFG=0x030,
                p_RXPHDLY_CFG=0x084020,
                p_RXPH_CFG=0xc00002,
                p_RX_DATA_WIDTH=20,
                i_RXCOMMADETEN=1,
                i_RXDLYBYPASS=1,
                i_RXDDIEN=0,
                o_RXDISPERR=Cat(rx_data[9], rx_data[19]),
                o_RXCHARISK=Cat(rx_data[8], rx_data[18]),
                o_RXDATA=Cat(rx_data[:8], rx_data[10:18]),

                # Polarity
                i_TXPOLARITY=0,
                i_RXPOLARITY=0,

                # Pads
                i_GTPRXP=data_pads.rxp,
                i_GTPRXN=data_pads.rxn,
                o_GTPTXP=data_pads.txp,
                o_GTPTXN=data_pads.txn
            )

        # Get 125MHz clocks back - the GTP junk insists on outputting 62.5MHz.
        txoutclk_rebuffer = Signal()
        self.specials += Instance("BUFG", i_I=self.txoutclk, o_O=txoutclk_rebuffer)
        rxoutclk_rebuffer = Signal()
        self.specials += Instance("BUFG", i_I=self.rxoutclk, o_O=rxoutclk_rebuffer)

        tx_mmcm_fb = Signal()
        tx_mmcm_reset = Signal()
        clk_tx_unbuf = Signal()
        clk_tx_half_unbuf = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=16e-9,
                i_CLKIN1=txoutclk_rebuffer,
                i_RST=tx_mmcm_reset,

                o_CLKFBOUT=tx_mmcm_fb,
                i_CLKFBIN=tx_mmcm_fb,

                p_CLKFBOUT_MULT_F=16,
                o_LOCKED=tx_mmcm_locked,
                p_DIVCLK_DIVIDE=1,

                p_CLKOUT0_DIVIDE_F=16,
                o_CLKOUT0=clk_tx_half_unbuf,
                p_CLKOUT1_DIVIDE=8,
                o_CLKOUT1=clk_tx_unbuf,
            ),
            Instance("BUFG", i_I=clk_tx_half_unbuf, o_O=self.cd_eth_tx_half.clk),
            Instance("BUFG", i_I=clk_tx_unbuf, o_O=self.cd_eth_tx.clk),
            AsyncResetSynchronizer(self.cd_eth_tx, ~tx_mmcm_locked)
        ]

        rx_mmcm_fb = Signal()
        rx_mmcm_reset = Signal()
        clk_rx_unbuf = Signal()
        clk_rx_half_unbuf = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=16e-9,
                i_CLKIN1=rxoutclk_rebuffer,
                i_RST=rx_mmcm_reset,

                o_CLKFBOUT=rx_mmcm_fb,
                i_CLKFBIN=rx_mmcm_fb,

                p_CLKFBOUT_MULT_F=16,
                o_LOCKED=rx_mmcm_locked,
                p_DIVCLK_DIVIDE=1,

                p_CLKOUT0_DIVIDE_F=16,
                o_CLKOUT0=clk_rx_half_unbuf,
                p_CLKOUT1_DIVIDE=8,
                o_CLKOUT1=clk_rx_unbuf,
            ),
            Instance("BUFG", i_I=clk_rx_half_unbuf, o_O=self.cd_eth_rx_half.clk),
            Instance("BUFG", i_I=clk_rx_unbuf, o_O=self.cd_eth_rx.clk),
            AsyncResetSynchronizer(self.cd_eth_rx, ~rx_mmcm_locked)
        ]

        # Transceiver init
        tx_init = GTPTxInit(sys_clk_freq)
        self.submodules += tx_init
        self.comb += [
            qpll_channel.reset.eq(tx_init.qpll_reset),
            tx_init.qpll_lock.eq(qpll_channel.lock),
            tx_reset.eq(tx_init.tx_reset)
        ]
        self.sync += tx_mmcm_reset.eq(~tx_init.done)
        tx_mmcm_reset.attr.add("no_retiming")

        rx_init = GTPRxInit(sys_clk_freq)
        self.submodules += rx_init
        self.comb += [
            rx_init.enable.eq(tx_init.done),
            rx_reset.eq(rx_init.rx_reset),
            
            rx_init.rx_pma_reset_done.eq(rx_pma_reset_done),
            drpaddr.eq(rx_init.drpaddr),
            drpen.eq(rx_init.drpen),
            drpdi.eq(rx_init.drpdi),
            rx_init.drprdy.eq(drprdy),
            rx_init.drpdo.eq(drpdo),
            drpwe.eq(rx_init.drpwe)
        ]

        # Gearbox and PCS connection
        gearbox = Gearbox()
        self.submodules += Gearbox()

        self.comb += [
            tx_data.eq(gearbox.tx_data_half),
            gearbox.rx_data_half.eq(rx_data),

            gearbox.tx_data.eq(pcs.tbi_tx),
            pcs.tbi_rx.eq(gearbox.rx_data)
        ]
