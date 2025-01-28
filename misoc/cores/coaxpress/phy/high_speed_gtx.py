from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.misc import WaitTimer
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.cores.coaxpress.common import word_layout
from misoc.cores.code_8b10b import Encoder, Decoder
from misoc.cores.gtx_7series_init import GTXInit, GTXInitPhaseAlignment
from misoc.interconnect.csr import *
from misoc.interconnect.stream import Endpoint


from functools import reduce
from operator import add


class HostRXPHYs(Module, AutoCSR):
    """
    A highspeed multilane RX phys that support reconfigurable linerate with 8b10b encoding
    Supported linerate: 1.25, 2.5, 3.125, 5, 6.25, 10, 12.5 Gbps 
    """
    def __init__(self, gt_refclk, pads, refclk_freq, master=0):
        assert master <= len(pads)
        
        self.qpll_reset = CSR()
        self.qpll_locked = CSRStatus()
        self.gtx_refclk_stable = CSRStorage()
        self.gtx_restart = CSR()

        # DRP port
        self.gtx_daddr = CSRStorage(9)
        self.gtx_dread = CSR()
        self.gtx_din_stb = CSR()
        self.gtx_din = CSRStorage(16)
        self.gtx_dout = CSRStatus(16)
        self.gtx_dready = CSR()

        self.phys = []
        # # #

        # For speed higher than 6.6Gbps, QPLL need to be used instead of CPLL - DS191 (v1.18.1) Table 9.1
        self.submodules.qpll = qpll = QPLL(gt_refclk)
        self.sync += self.qpll_locked.status.eq(qpll.lock)

        for i, pad in enumerate(pads):
            if len(pads) == 1:
                rx_mode = "single"
            else:
                rx_mode = "master" if i == master else "slave"
            rx = Receiver(qpll, pad, refclk_freq, rx_mode)
            self.phys.append(rx)
            setattr(self.submodules, "rx"+str(i), rx)

        for i, phy in enumerate(self.phys):
            if i == master:
                # Connect master GTX connections' output DRP
                self.sync += [
                    If(phy.gtx.dready,
                        self.gtx_dready.w.eq(1),
                        self.gtx_dout.status.eq(phy.gtx.dout),
                    ).Elif(self.gtx_dready.re,
                        self.gtx_dready.w.eq(0),
                    ),
                ]
            self.sync += [
                phy.gtx.qpll_reset.eq(self.qpll_reset.re),
                phy.gtx.refclk_ready.eq(self.gtx_refclk_stable.storage),
                phy.gtx.rx_restart.eq(self.gtx_restart.re),
            ]

            # Connect all GTX connections' input DRP
            self.sync += [
                phy.gtx.daddr.eq(self.gtx_daddr.storage),
                phy.gtx.den.eq(self.gtx_dread.re | self.gtx_din_stb.re),
                phy.gtx.dwen.eq(self.gtx_din_stb.re),
                phy.gtx.din.eq(self.gtx_din.storage),
            ]
            self.comb += phy.gtx.dclk.eq(ClockSignal("sys"))

        # master rx_init will lock up when slaves_phaligndone signal is not connected
        self.submodules.rx_phase_alignment = GTXInitPhaseAlignment([rx_phy.gtx.rx_init for rx_phy in self.phys])


class Receiver(Module):
    def __init__(self, qpll, pad, refclk_freq, rx_mode):
        self.submodules.gtx = gtx = GTX(qpll, pad, refclk_freq, None, rx_mode)
       
        self.source = Endpoint(word_layout)

        data_valid = Signal()
        self.sync.cxp_gt_rx += [
            data_valid.eq(gtx.comma_aligner.rxfsm.ongoing("READY")),

            self.source.stb.eq(0),
            If(data_valid & ~((gtx.decoders[0].d == 0xBC) & (gtx.decoders[0].k == 1)),
                self.source.stb.eq(1),
                self.source.data.eq(Cat(gtx.decoders[i].d for i in range(4))),
                self.source.k.eq(Cat(gtx.decoders[i].k for i in range(4))),
            )
        ]


class QPLL(Module, AutoCSR):
    """
    A frequency reconfigurable QPLL
    Designed for 125 MHz gt refclk

    The following QPLL settings only need upper band VCO (9.8-12.5 GHz) for all CXP linerate

     linerate    GT REFCLK  Feedback   R/TXOut   |   VCO
      (Gbps)     Divider    Divider    Divider   |  (GHz)
    ──────────  ────────── ────────── ────────── | ───────
       1.25         1         80         8       |   10
       2.5          1         80         4       |   10
       3.125        1         100        4       |   12.5
       5            1         80         2       |   10
       6.25         1         100        2       |   12.5
       10           1         80         1       |   10
       12.5         1         100        1       |   12.5
    
    Initial setting: linerate @ 1.25 Gbps
    """
    def __init__(self, gt_refclk):
        self.clk = Signal()
        self.refclk = Signal()
        self.lock = Signal()
        self.reset = Signal()

        self.daddr = CSRStorage(8)
        self.dread = CSR()
        self.din_stb = CSR()
        self.din = CSRStorage(16)

        self.dout = CSRStatus(16)
        self.dready = CSR()

        # # #

        # feedback divider = 80, refclk divider = 1 and R/Txout divider = 8
        # refclk @ 125 MHz => VCO = 125*80/1 MHz = 10GHz and linerate = 10/8 Gbps = 1.25Gbps
        qpll_fbdiv = 0b0100100000
        qpll_fbdiv_ratio = 1
        self.fbdiv = 80
        self.refclk_div = 1
        self.Xxout_div = 8

        dready = Signal()
        self.specials += [
            Instance("GTXE2_COMMON",
                i_QPLLREFCLKSEL=0b001,
                i_GTREFCLK0=gt_refclk,         

                i_QPLLPD=0,
                i_QPLLRESET=self.reset,
                i_QPLLLOCKEN=1,
                o_QPLLLOCK=self.lock,
                o_QPLLOUTCLK=self.clk,
                o_QPLLOUTREFCLK=self.refclk,

                # See UG476 (v1.12.1) Table 2-16
                p_QPLL_FBDIV=qpll_fbdiv,
                p_QPLL_FBDIV_RATIO=qpll_fbdiv_ratio,
                p_QPLL_REFCLK_DIV=self.refclk_div,

                # From 7 Series FPGAs Transceivers Wizard
                p_BIAS_CFG=0x0000040000001000,
                p_COMMON_CFG=0x00000000,
                p_QPLL_CFG=0x0680181,
                p_QPLL_CLKOUT_CFG=0b0000,
                p_QPLL_COARSE_FREQ_OVRD=0b010000,
                p_QPLL_COARSE_FREQ_OVRD_EN=0b0,
                p_QPLL_CP=0b0000011111,
                p_QPLL_CP_MONITOR_EN=0b0,
                p_QPLL_DMONITOR_SEL=0b0,
                p_QPLL_FBDIV_MONITOR_EN= 0b0,
                p_QPLL_INIT_CFG=0x000006,
                p_QPLL_LOCK_CFG=0x21E8,
                p_QPLL_LPF=0b1111,
             
                # Reserved, values cannot be modified
                i_BGBYPASSB=0b1,
                i_BGMONITORENB=0b1,
                i_BGPDB=0b1,
                i_BGRCALOVRD=0b11111,
                i_RCALENB=0b1,
                i_QPLLRSVD1=0b0,
                i_QPLLRSVD2=0b11111,

                # Dynamic Reconfiguration Ports
                i_DRPADDR=self.daddr.storage,
                i_DRPCLK=ClockSignal("sys"),
                i_DRPEN=(self.dread.re | self.din_stb.re),
                i_DRPWE=self.din_stb.re,
                i_DRPDI=self.din.storage,
                o_DRPDO=self.dout.status,
                o_DRPRDY=dready,
            )
        ]

        self.sync += [
            If(dready,
               self.dready.w.eq(1),
            ),
            If(self.dready.re,
               self.dready.w.eq(0),
            ),
        ]


class Comma_Aligner(Module):
    """
    Xilinx transceivers are LSB first, and comma needs to be flipped
    compared to the usual 8b10b binary representation.
    """
    def __init__(self, comma):
        self.data = Signal(10)
        self.comma_aligned = Signal()
        self.comma_realigned = Signal()
        self.comma_det = Signal()

        self.aligner_en = Signal()
        self.ready_sys = Signal()

        # # #

        # From UG476 (v1.12.1) p.228
        # The built-in RXBYTEISALIGNED can be falsely asserted at linerate higher than 5Gbps
        # The validity of data and comma needed to be checked externally

        comma_n = ~comma & 0b1111111111

        comma_seen = Signal()
        error_seen = Signal()
        one_counts = Signal(max=11)

        # From CXP-001-2021 section 9.2.5.1
        # For high speed connection an IDLE word shall be transmitted at least once every 100 words
        counter_period = 200

        counter = Signal(reset=counter_period-1, max=counter_period)
        check_reset = Signal()
        check = Signal()

        self.sync.cxp_gt_rx += [
            If(check_reset,
                counter.eq(counter.reset),   
                check.eq(0),
            ).Elif(counter == 0,
                check.eq(1),
            ).Else(
                counter.eq(counter - 1),   
            ),

            If(check_reset,
                comma_seen.eq(0),
            ).Elif((self.data[:10] == comma) | (self.data[:10] == comma_n),
                comma_seen.eq(1)
            ),

            one_counts.eq(reduce(add, [self.data[i] for i in range(10)])),
            If(check_reset,
                error_seen.eq(0),
            ).Elif((one_counts != 4) & (one_counts != 5) & (one_counts != 6),
                error_seen.eq(1),
            ),

        ]

        self.submodules.rxfsm = rxfsm = ClockDomainsRenamer("cxp_gt_rx")(FSM(reset_state="WAIT_COMMA"))

        rxfsm.act("WAIT_COMMA",
            If(self.comma_det,
                NextState("ALIGNING"),
            )
        )

        rxfsm.act("ALIGNING",
            If(self.comma_aligned & (~self.comma_realigned),
                NextState("WAIT_ALIGNED_DATA"),               
            ).Else(
                self.aligner_en.eq(1),
            )
        )

        # From UG476 (v1.12.1) p.232
        # wait for the aligned data to arrive at the FPGA RX interface 
        # as there is a delay before the data is available after RXBYTEISALIGNED is asserted
        self.submodules.timer = timer = ClockDomainsRenamer("cxp_gt_rx")(WaitTimer(10_000))

        rxfsm.act("WAIT_ALIGNED_DATA",
            timer.wait.eq(1),
            check_reset.eq(1),
            If(timer.done,
                NextState("CHECKING"),
            )
        )

        rxfsm.act("CHECKING",
            If(check,
                check_reset.eq(1),
                If(comma_seen & (~error_seen),
                    NextState("READY"),
                ).Else(
                    NextState("WAIT_COMMA")
                )
            )
        )

        ready = Signal()
        self.specials += MultiReg(ready, self.ready_sys)
        rxfsm.act("READY",
            ready.eq(1),
            If(check,
                check_reset.eq(1),
                If(~(comma_seen & (~error_seen)),
                    NextState("WAIT_COMMA"),
                )
            )
        )


class GTX(Module):
    """
    A linerate reconfigurable 40bit width GTX with QPLL
    Designed for 1.25, 2.5, 3.125, 5, 6.25, 10, 12.5 Gpbs

    To change the linerate:
    1) Change the QPLL VCO frequency
    2) Update the TXOUT_DIV and TXUSRCLK frequency if using tx
    3) Update the RXOUT_DIV and RXCDR_CFG if using rx
    4) Reset the entire rx/tx
    """
    def __init__(self, qpll, pads, refclk_freq, tx_mode="single", rx_mode="single"):
        assert tx_mode in ["single", "master", "slave", None]
        assert rx_mode in ["single", "master", "slave", None]


        self.refclk_ready = Signal()
        self.qpll_reset = Signal()
        self.tx_restart = Signal()
        self.rx_restart = Signal()
        self.loopback_mode = Signal(3)

        self.txenable = Signal()
        self.rx_ready = Signal()

        # Dynamic Reconfiguration Ports
        self.daddr = Signal(9)
        self.dclk = Signal()
        self.den = Signal()
        self.dwen = Signal()
        self.din = Signal(16)
        self.dout = Signal(16)
        self.dready = Signal()



        # transceiver direct clock outputs
        # useful to specify clock constraints in a way palatable to Vivado
        self.txoutclk = Signal()
        self.rxoutclk = Signal()

        # # #

        txdata = Signal(40)
        rxdata = Signal(40)

        if tx_mode:
            self.submodules.tx_init = tx_init = GTXInit(refclk_freq, False, mode=tx_mode)
            self.sync += [
                tx_init.cplllock.eq(qpll.lock),
                tx_init.clk_path_ready.eq(self.refclk_ready),
                # qpll reset are hold high before gtxinit, otherwise GTXINIT FSM may sometimes lock up as
                # qpll lock doesn't always deassert the next cycle after qpll reset = 1
                If(self.refclk_ready,
                    qpll.reset.eq(tx_init.cpllreset | self.qpll_reset),
                ).Else(
                    qpll.reset.eq(1),
                )
            ]

            self.submodules.encoder = ClockDomainsRenamer("cxp_gt_tx")(Encoder(4, True))
            self.comb += txdata.eq(Cat(self.encoder.output[0], self.encoder.output[1], self.encoder.output[2], self.encoder.output[3])),

        if rx_mode:
            self.submodules.rx_init = rx_init = GTXInit(refclk_freq, True, mode=rx_mode)
            self.sync += [
                rx_init.cplllock.eq(qpll.lock),
                rx_init.clk_path_ready.eq(self.refclk_ready),
            ]
            if not tx_mode:
                # qpll reset are hold high before gtxinit, otherwise GTXINIT FSM may sometimes lock up as
                # qpll lock doesn't always deassert the next cycle after qpll reset = 1
                self.sync += \
                    If(self.refclk_ready,
                        qpll.reset.eq(rx_init.cpllreset | self.qpll_reset),
                    ).Else(
                        qpll.reset.eq(1),
                    )

            self.submodules.decoders = [ClockDomainsRenamer("cxp_gt_rx")(
                (Decoder(True))) for _ in range(4)]
            self.comb += [
                self.decoders[0].input.eq(rxdata[:10]),
                self.decoders[1].input.eq(rxdata[10:20]),
                self.decoders[2].input.eq(rxdata[20:30]),
                self.decoders[3].input.eq(rxdata[30:]),
            ]

        comma_aligned = Signal()
        comma_realigned = Signal()
        comma_det = Signal()
        comma_aligner_en = Signal()
        # Note: the following parameters were set after consulting AR45360
        self.specials += \
            Instance("GTXE2_CHANNEL",
                # PMA Attributes
                p_PMA_RSV=0x001E7080,
                p_PMA_RSV2=0x2050,              # PMA_RSV2[5] = 0: Eye scan feature disabled
                p_PMA_RSV3=0,
                p_PMA_RSV4=1,                   # PMA_RSV[4],RX_CM_TRIM[2:0] = 0b1010: Common mode 800mV
                p_RX_BIAS_CFG=0b000000000100,
                p_RX_OS_CFG=0b0000010000000,
                p_RX_CLK25_DIV=5,
                p_TX_CLK25_DIV=5,

                # Power-Down Attributes
                p_PD_TRANS_TIME_FROM_P2=0x3c,
                p_PD_TRANS_TIME_NONE_P2=0x3c,
                p_PD_TRANS_TIME_TO_P2=0x64,
                i_CPLLPD=1,

                # Transceiver Reset Mode Operation
                i_GTRESETSEL       = 0, # sequential mode
                i_RESETOVRD        = 0,
                
                # QPLL
                i_QPLLCLK=qpll.clk,
                i_QPLLREFCLK=qpll.refclk,
                p_RXOUT_DIV=qpll.Xxout_div,
                p_TXOUT_DIV=qpll.Xxout_div,
                i_RXSYSCLKSEL=0b11, # use QPLL & QPLL's REFCLK
                i_TXSYSCLKSEL=0b11, # use QPLL & CPLL's REFCLK

                # TX clock
                p_TXBUF_EN="FALSE",
                p_TX_XCLK_SEL="TXUSR",
                o_TXOUTCLK=self.txoutclk,
                # i_TXSYSCLKSEL=0b00,
                i_TXOUTCLKSEL=0b11,

                # TX Startup/Reset
                i_TXPHDLYRESET=0,
                i_TXDLYBYPASS=0,
                i_TXPHALIGNEN=1 if tx_mode in ["master", "slave"] else 0,
                i_GTTXRESET=tx_init.gtXxreset if tx_mode else 0,
                o_TXRESETDONE=tx_init.Xxresetdone if tx_mode else 0,
                i_TXDLYSRESET=tx_init.Xxdlysreset if tx_mode else 0,
                o_TXDLYSRESETDONE=tx_init.Xxdlysresetdone if tx_mode else 0,
                i_TXPHINIT=tx_init.txphinit if tx_mode in ["master", "slave"] else 0,
                o_TXPHINITDONE=tx_init.txphinitdone if tx_mode in ["master", "slave"] else Signal(),
                i_TXPHALIGN=tx_init.Xxphalign if tx_mode in ["master", "slave"] else 0,
                i_TXDLYEN=tx_init.Xxdlyen if tx_mode in ["master", "slave"] else 0,
                o_TXPHALIGNDONE=tx_init.Xxphaligndone if tx_mode else 0,
                i_TXUSERRDY=tx_init.Xxuserrdy if tx_mode else 0,
                p_TXPMARESET_TIME=1,
                p_TXPCSRESET_TIME=1,
                i_TXINHIBIT=~self.txenable,

                # TX data
                p_TX_DATA_WIDTH=40,
                p_TX_INT_DATAWIDTH=1, # 1 if a line rate is greater than 6.6 Gbps
                i_TXCHARDISPMODE=Cat(txdata[9], txdata[19], txdata[29], txdata[39]),
                i_TXCHARDISPVAL=Cat(txdata[8], txdata[18], txdata[28], txdata[38]),
                i_TXDATA=Cat(txdata[:8], txdata[10:18], txdata[20:28], txdata[30:38]),
                i_TXUSRCLK=ClockSignal("cxp_gt_tx") if tx_mode else 0,
                i_TXUSRCLK2=ClockSignal("cxp_gt_tx") if tx_mode else 0,

                # TX electrical
                i_TXBUFDIFFCTRL=0b100,
                i_TXDIFFCTRL=0b1000,

                # RX Startup/Reset
                i_RXPHDLYRESET=0,
                i_RXDLYBYPASS=0,
                i_RXPHALIGNEN=1 if rx_mode in ["master", "slave"] else 0,
                i_GTRXRESET=rx_init.gtXxreset if rx_mode else 0,
                o_RXRESETDONE=rx_init.Xxresetdone if rx_mode else 0,
                i_RXDLYSRESET=rx_init.Xxdlysreset if rx_mode else 0,
                o_RXDLYSRESETDONE=rx_init.Xxdlysresetdone if rx_mode else 0,
                i_RXPHALIGN=rx_init.Xxphalign if rx_mode in ["master", "slave"] else 0,
                i_RXDLYEN=rx_init.Xxdlyen if rx_mode in ["master", "slave"] else 0,
                o_RXPHALIGNDONE=rx_init.Xxphaligndone if rx_mode else 0,
                i_RXUSERRDY=rx_init.Xxuserrdy if rx_mode else 0,
                p_RXPMARESET_TIME=1,
                p_RXPCSRESET_TIME=1,

                # RX AFE
                p_RX_DFE_XYD_CFG=0,
                p_RX_CM_SEL=0b11,               # RX_CM_SEL = 0b11: Common mode is programmable
                p_RX_CM_TRIM=0b010,             # PMA_RSV[4],RX_CM_TRIM[2:0] = 0b1010: Common mode 800mV
                i_RXDFEXYDEN=1,
                i_RXDFEXYDHOLD=0,
                i_RXDFEXYDOVRDEN=0,
                i_RXLPMEN=1,                    # RXLPMEN = 1: LPM mode is enable for non scramble 8b10b data
                p_RXLPM_HF_CFG=0b00000011110000,
                p_RXLPM_LF_CFG=0b00000011110000,

                p_RX_DFE_GAIN_CFG=0x0207EA,
                p_RX_DFE_VP_CFG=0b00011111100000011,
                p_RX_DFE_UT_CFG=0b10001000000000000,
                p_RX_DFE_KL_CFG=0b0000011111110,
                p_RX_DFE_KL_CFG2=0x3788140A,
                p_RX_DFE_H2_CFG=0b000110000000,
                p_RX_DFE_H3_CFG=0b000110000000,
                p_RX_DFE_H4_CFG=0b00011100000,
                p_RX_DFE_H5_CFG=0b00011100000,
                p_RX_DFE_LPM_CFG=0x0904,        # RX_DFE_LPM_CFG = 0x0904: linerate <= 6.6Gb/s
                                                #                = 0x0104: linerate > 6.6Gb/s

                # RX clock
                i_RXDDIEN=1,
                i_RXOUTCLKSEL=0b010,
                o_RXOUTCLK=self.rxoutclk,
                i_RXUSRCLK=ClockSignal("cxp_gt_rx") if rx_mode else 0,
                i_RXUSRCLK2=ClockSignal("cxp_gt_rx") if rx_mode else 0,

                # RX Clock Correction Attributes
                p_CLK_CORRECT_USE="FALSE",
                p_CLK_COR_SEQ_1_1=0b0100000000,
                p_CLK_COR_SEQ_2_1=0b0100000000,
                p_CLK_COR_SEQ_1_ENABLE=0b1111,
                p_CLK_COR_SEQ_2_ENABLE=0b1111,

                # RX data
                p_RX_DATA_WIDTH=40,
                p_RX_INT_DATAWIDTH=1,   # 1 if a line rate is greater than 6.6 Gbps
                o_RXDISPERR=Cat(rxdata[9], rxdata[19], rxdata[29], rxdata[39]),
                o_RXCHARISK=Cat(rxdata[8], rxdata[18], rxdata[28], rxdata[38]),
                o_RXDATA=Cat(rxdata[:8], rxdata[10:18], rxdata[20:28], rxdata[30:38]),

                # RX Byte and Word Alignment Attributes
                p_ALIGN_COMMA_DOUBLE="FALSE",
                p_ALIGN_COMMA_ENABLE=0b1111111111,
                p_ALIGN_COMMA_WORD=4, # align comma to rxdata[:10] only
                p_ALIGN_MCOMMA_DET="TRUE",
                p_ALIGN_MCOMMA_VALUE=0b1010000011,
                p_ALIGN_PCOMMA_DET="TRUE",
                p_ALIGN_PCOMMA_VALUE=0b0101111100,
                p_SHOW_REALIGN_COMMA="FALSE",
                p_RXSLIDE_AUTO_WAIT=7,
                p_RXSLIDE_MODE="OFF",
                p_RX_SIG_VALID_DLY=10,
                i_RXPCOMMAALIGNEN=comma_aligner_en,
                i_RXMCOMMAALIGNEN=comma_aligner_en,
                i_RXCOMMADETEN=1,
                i_RXSLIDE=0,
                o_RXBYTEISALIGNED=comma_aligned,
                o_RXBYTEREALIGN=comma_realigned,
                o_RXCOMMADET=comma_det,

                # RX 8B/10B Decoder Attributes
                p_RX_DISPERR_SEQ_MATCH="FALSE",
                p_DEC_MCOMMA_DETECT="TRUE",
                p_DEC_PCOMMA_DETECT="TRUE",
                p_DEC_VALID_COMMA_ONLY="FALSE",

                # RX Buffer Attributes
                p_RXBUF_ADDR_MODE="FAST",
                p_RXBUF_EIDLE_HI_CNT=0b1000,
                p_RXBUF_EIDLE_LO_CNT=0b0000,
                p_RXBUF_EN="FALSE",
                p_RX_BUFFER_CFG=0b000000,
                p_RXBUF_RESET_ON_CB_CHANGE="TRUE",
                p_RXBUF_RESET_ON_COMMAALIGN="FALSE",
                p_RXBUF_RESET_ON_EIDLE="FALSE",     # RXBUF_RESET_ON_EIDLE = FALSE: OOB is disabled
                p_RXBUF_RESET_ON_RATE_CHANGE="TRUE",
                p_RXBUFRESET_TIME=0b00001,
                p_RXBUF_THRESH_OVFLW=61,
                p_RXBUF_THRESH_OVRD="FALSE",
                p_RXBUF_THRESH_UNDFLW=4,
                p_RXDLY_CFG=0x001F,
                p_RXDLY_LCFG=0x030,
                p_RXDLY_TAP_CFG=0x0000,
                p_RXPH_CFG=0xC00002,
                p_RXPHDLY_CFG=0x084020,
                p_RXPH_MONITOR_SEL=0b00000,
                p_RX_XCLK_SEL="RXUSR",
                p_RX_DDI_SEL=0b000000,
                p_RX_DEFER_RESET_BUF_EN="TRUE",

                # CDR Attributes
                p_RXCDR_CFG=0x03_0000_23FF_1008_0020,   # LPM @ 0.5G-1.5625G , 8B/10B encoded data, CDR setting < +/- 200ppm
                                                        # (See UG476 (v1.12.1), p.206)
                p_RXCDR_FR_RESET_ON_EIDLE=0b0,
                p_RXCDR_HOLD_DURING_EIDLE=0b0,
                p_RXCDR_PH_RESET_ON_EIDLE=0b0,
                p_RXCDR_LOCK_CFG=0b010101,

                # Pads
                i_GTXRXP=pads.rxp if rx_mode else 0,
                i_GTXRXN=pads.rxn if rx_mode else 0,
                o_GTXTXP=pads.txp if tx_mode else 0,
                o_GTXTXN=pads.txn if tx_mode else 0,

                # Dynamic Reconfiguration Ports
                p_IS_DRPCLK_INVERTED=0b0,
                i_DRPADDR=self.daddr,
                i_DRPCLK=self.dclk,
                i_DRPEN=self.den,
                i_DRPWE=self.dwen,
                i_DRPDI=self.din,
                o_DRPDO=self.dout,
                o_DRPRDY=self.dready,

                # Nearend Loopback
                i_LOOPBACK = self.loopback_mode,
                p_TX_LOOPBACK_DRIVE_HIZ = "FALSE",
                p_RXPRBS_ERR_LOOPBACK = 0b0,

                # Other parameters
                p_PCS_RSVD_ATTR=(
                    (tx_mode != "single") << 1 |    # PCS_RSVD_ATTR[1] = 0: TX Single Lane Auto Mode
                                                    #                  = 1: TX Manual Mode
                    (rx_mode != "single") << 2 |    #              [2] = 0: RX Single Lane Auto Mode
                                                    #                  = 1: RX Manual Mode
                    0 << 8                          #              [8] = 0: OOB is disabled
                ),
                i_RXELECIDLEMODE=0b11,              # RXELECIDLEMODE = 0b11: OOB is disabled
                p_RX_DFE_LPM_HOLD_DURING_EIDLE=0b0,
                p_ES_EYE_SCAN_EN="TRUE",            # Must be TRUE for GTX
            )


        # TX clocking
        # When bypassing the TX buffer and changing frequency of VCO of QPLL/CPLL,
        # TXUSRCLK rate will always be the refclk rate.
        # To match the required TXUSRCLK rate = linerate/datewidth (UG476 (v1.12.1) Equation 3-1), a DRP PLL is used.
         
        # Slave TX will use cxp_gt_tx from master
        if tx_mode == "single" or tx_mode == "master":
            self.clock_domains.cd_cxp_gt_tx = ClockDomain()
            txpll_fb_clk = Signal()
            txoutclk_buf = Signal()
            txpll_clkout = Signal()

            self.txpll_reset = Signal()
            self.pll_daddr = Signal(7)
            self.pll_dclk = Signal()
            self.pll_den = Signal()
            self.pll_din = Signal(16)
            self.pll_dwen = Signal()

            self.txpll_locked = Signal()
            self.pll_dout = Signal(16)
            self.pll_dready = Signal()

            pll_fbout_mult = 8
            tx_usrclk_freq = ((refclk_freq*qpll.fbdiv)/(qpll.Xxout_div*qpll.refclk_div))/40
            txusr_pll_div = pll_fbout_mult*refclk_freq/tx_usrclk_freq
            self.specials += [
                Instance("PLLE2_ADV",
                    p_BANDWIDTH="HIGH",
                    o_LOCKED=self.txpll_locked,
                    i_RST=self.txpll_reset,
                
                    p_CLKIN1_PERIOD=1e9/refclk_freq, # ns
                    i_CLKIN1=txoutclk_buf,

                    # VCO @ 1.25GHz 
                    p_CLKFBOUT_MULT=pll_fbout_mult, p_DIVCLK_DIVIDE=1,
                    i_CLKFBIN=txpll_fb_clk, o_CLKFBOUT=txpll_fb_clk, 

                    # frequency = linerate/40
                    p_CLKOUT0_DIVIDE=txusr_pll_div, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=txpll_clkout,

                    # Dynamic Reconfiguration Ports
                    i_DADDR = self.pll_daddr,
                    i_DCLK = self.pll_dclk,
                    i_DEN = self.pll_den,
                    i_DI = self.pll_din,
                    i_DWE = self.pll_dwen,
                    o_DO = self.pll_dout,
                    o_DRDY = self.pll_dready,
                ),
                Instance("BUFG", i_I=self.txoutclk, o_O=txoutclk_buf),
                Instance("BUFG", i_I=txpll_clkout, o_O=self.cd_cxp_gt_tx.clk),
                AsyncResetSynchronizer(self.cd_cxp_gt_tx, ~self.txpll_locked & ~tx_init.done)
            ]
            self.comb += tx_init.restart.eq(self.tx_restart)

        # RX clocking
        # When frequency of VCO of QPLL/CPLL is changed, RXUSRCLK will match the required frequency
        # RXUSRCLK rate = linerate/datewidth (UG476 (v1.12.1) Equation 4-2). And PLL is not needed.
        
        # Slave RX will use cxp_gt_rx from master
        if rx_mode == "single" or rx_mode == "master":
            self.clock_domains.cd_cxp_gt_rx = ClockDomain()
            self.specials += Instance("BUFG", i_I=self.rxoutclk, o_O=self.cd_cxp_gt_rx.clk),
            # rxuserrdy is driven high when RXUSRCLK and RXUSRCLK2 are stable - UG476 (v1.12.1) p.75
            self.specials += AsyncResetSynchronizer(self.cd_cxp_gt_rx, ~rx_init.Xxuserrdy)

        if rx_mode:
            self.comb += rx_init.restart.eq(self.rx_restart)

            self.submodules.comma_aligner = comma_aligner = Comma_Aligner(0b0101111100)
            self.sync.cxp_gt_rx += [
                comma_aligner.data.eq(rxdata),
                comma_aligner.comma_aligned.eq(comma_aligned),
                comma_aligner.comma_realigned.eq(comma_realigned),
                comma_aligner.comma_det.eq(comma_det),
                comma_aligner_en.eq(comma_aligner.aligner_en),
                self.rx_ready.eq(comma_aligner.ready_sys),
            ]
