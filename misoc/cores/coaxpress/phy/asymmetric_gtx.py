from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.cores.coaxpress.common import char_layout, word_layout
from misoc.cores.coaxpress.phy.high_speed_gtx import QPLL, CommaAligner
from misoc.cores.coaxpress.phy.low_speed_serdes import ClockGen 
from misoc.cores.code_8b10b import Decoder, SingleEncoder
from misoc.cores.gtx_7series_init import GTXInit, GTXInitPhaseAlignment
from misoc.interconnect.csr import *
from misoc.interconnect.stream import Endpoint


class HostTRXPHYs(Module, AutoCSR):
    """
    A asymmetric multilane TRX phys that support reconfigurable linerate with 8b10b encoding
    TX supported linerate: 20.83, 41.6 Mbps
    RX supported linerate: 1.25, 2.5, 3.125, 5, 6.25, 10, 12.5 Gbps 
    """
    def __init__(self, gt_refclk, pads, refclk_freq, master=0):
        assert master <= len(pads)
        self.tx_clk_reset = CSR()
        self.tx_bitrate2x_enable = CSRStorage()
        self.tx_enable = CSRStorage()

        self.rx_qpll_reset = CSR()
        self.rx_qpll_locked = CSRStatus()
        self.rx_gtx_refclk_stable = CSRStorage()
        self.rx_gtx_restart = CSR()

        # DRP port
        self.rx_gtx_daddr = CSRStorage(9)
        self.rx_gtx_dread = CSR()
        self.rx_gtx_din_stb = CSR()
        self.rx_gtx_din = CSRStorage(16)
        self.rx_gtx_dout = CSRStatus(16)
        self.rx_gtx_dready = CSR()

        # For speed higher than 6.6Gbps, QPLL need to be used instead of CPLL - DS191 (v1.18.1) Table 9.1
        self.submodules.rx_qpll = qpll = QPLL(gt_refclk)
        self.sync += self.rx_qpll_locked.status.eq(qpll.lock)

        self.phys = []
        for i, pad in enumerate(pads):
            if len(pads) == 1:
                rx_mode = "single"
            else:
                rx_mode = "master" if i == master else "slave"
            trx = Transceiver(gt_refclk, qpll, pad, refclk_freq, rx_mode)
            self.phys.append(trx)
            setattr(self.submodules, "trx"+str(i), trx)

        for i, phy in enumerate(self.phys):
            if i == master:
                # Connect master GTX connections' output DRP
                self.sync += [
                    If(phy.gtx.dready,
                        self.rx_gtx_dready.w.eq(1),
                        self.rx_gtx_dout.status.eq(phy.gtx.dout),
                    ).Elif(self.rx_gtx_dready.re,
                        self.rx_gtx_dready.w.eq(0),
                    ),
                ]
            self.sync += [
                phy.bitrate2x_enable.eq(self.tx_bitrate2x_enable.storage),
                phy.cg_reset.eq(self.tx_clk_reset.re),
                phy.tx_enable.eq(self.tx_enable.storage),

                phy.gtx.qpll_reset.eq(self.rx_qpll_reset.re),
                phy.gtx.refclk_ready.eq(self.rx_gtx_refclk_stable.storage),
                phy.gtx.rx_restart.eq(self.rx_gtx_restart.re),

                # Connect all GTX connections' input DRP
                phy.gtx.daddr.eq(self.rx_gtx_daddr.storage),
                phy.gtx.den.eq(self.rx_gtx_dread.re | self.rx_gtx_din_stb.re),
                phy.gtx.dwen.eq(self.rx_gtx_din_stb.re),
                phy.gtx.din.eq(self.rx_gtx_din.storage),
            ]
            self.comb += phy.gtx.dclk.eq(ClockSignal("sys"))


        # master rx_init will lock up when slaves_phaligndone signal is not connected
        self.submodules.rx_phase_alignment = GTXInitPhaseAlignment([trx_phy.gtx.rx_init for trx_phy in self.phys])

class Transceiver(Module):
    def __init__(self, gt_refclk, qpll, pad, refclk_freq, rx_mode):
        self.bitrate2x_enable = Signal()
        self.cg_reset = Signal()
        self.tx_enable = Signal()

        # # #
         
        self.submodules.gtx = gtx = AsymmetricGTX(gt_refclk, qpll, pad, refclk_freq, "single", rx_mode)

        # TX
        self.sink = Endpoint(char_layout)
        self.submodules.encoder = encoder = SingleEncoder(True)
        self.submodules.cg = cg = ClockGen(refclk_freq)
        self.comb += [
            cg.reset.eq(self.cg_reset),
            cg.freq2x_enable.eq(self.bitrate2x_enable),
        ]

        tx_bitcount = Signal(max=10)
        tx_reg = Signal(10)
        self.sync += [
            gtx.tx_enable.eq(self.tx_enable),
            If(self.tx_enable & ~self.cg_reset,
                self.sink.ack.eq(0),
                # Encode the 8-bit char into 10-bit
                If(cg.clk,
                    encoder.disp_in.eq(encoder.disp_out),
                    self.sink.ack.eq(1),
                    encoder.d.eq(self.sink.data),
                    encoder.k.eq(self.sink.k),
                ),
                # Serialize the encoder char
                If(cg.clk_10x,
                    # tie all txdata bits together and send LSB first
                    [gtx.txdata[i].eq(tx_reg[0]) for i in range(len(gtx.txdata))],
                    tx_reg.eq(Cat(tx_reg[1:], 0)),
                    tx_bitcount.eq(tx_bitcount + 1),   
                    If(tx_bitcount == 9,
                        tx_bitcount.eq(0),
                        tx_reg.eq(encoder.output),
                    ),
                ),
            ).Else(
                # Discard packets and send D00.0 when TX is not active (CXP-001-2021 section 12.1.1)
                self.sink.ack.eq(1),
                [gtx.txdata[i].eq(0) for i in range(len(gtx.txdata))],
                tx_bitcount.eq(0),
                tx_reg.eq(0),
            )
        ]
        
        # RX
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


class AsymmetricGTX(Module):
    """
    A 40bit width GTX with reconfigurable RX linerate and fixed TX linerate
    The RX is designed to run at 1.25, 2.5, 3.125, 5, 6.25, 10, 12.5 Gpbs
    The TX is designed to run at 5 Gbps 

    To change the RX linerate:
    1) Change the QPLL VCO frequency
    2) Update the RXOUT_DIV and RXCDR_CFG
    3) Reset the entire RX
    """
    def __init__(self, gt_refclk, qpll, pads, refclk_freq, tx_mode="single", rx_mode="single"):
        assert tx_mode in ["single", "master", "slave"]
        assert rx_mode in ["single", "master", "slave"]

        self.refclk_ready = Signal()
        self.qpll_reset = Signal()
        self.rx_restart = Signal()
        self.loopback_mode = Signal(3)

        self.tx_enable = Signal()
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

        self.txdata = Signal(40)
        rxdata = Signal(40)

        cplllock = Signal()
        cpllreset = Signal()
        self.submodules.tx_init = tx_init = GTXInit(refclk_freq, False, mode=tx_mode)
        self.sync += [
            tx_init.cplllock.eq(cplllock),
            tx_init.clk_path_ready.eq(self.refclk_ready),
            cpllreset.eq(tx_init.cpllreset),
        ]

        self.submodules.rx_init = rx_init = GTXInit(refclk_freq, True, mode=rx_mode)
        self.sync += [
            rx_init.cplllock.eq(qpll.lock),
            rx_init.clk_path_ready.eq(self.refclk_ready),
            # qpll reset are hold high before gtxinit, otherwise GTXINIT FSM may sometimes lock up as
            # qpll lock doesn't always deassert the next cycle after qpll reset = 1
            If(self.refclk_ready,
                qpll.reset.eq(rx_init.cpllreset | self.qpll_reset),
            ).Else(
                qpll.reset.eq(1),
            )
        ]

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

                # Transceiver Reset Mode Operation
                i_GTRESETSEL       = 0, # sequential mode
                i_RESETOVRD        = 0,
                
                # CPLL for TX
                p_CPLL_CFG=0xBC07DC,
                p_CPLL_FBDIV=4,
                p_CPLL_FBDIV_45=5,
                p_CPLL_REFCLK_DIV=1,
                p_CPLL_INIT_CFG=0x00001E,
                p_CPLL_LOCK_CFG=0x01E8,
                i_GTREFCLK0=gt_refclk,
                i_CPLLRESET=cpllreset,
                i_CPLLPD=cpllreset,
                i_CPLLLOCKEN=1,
                i_CPLLREFCLKSEL=0b001,
                o_CPLLLOCK=cplllock,
                p_TXOUT_DIV=1,
                i_TXSYSCLKSEL=0b00, # use CPLL & CPLL's REFCLK

                # QPLL for RX
                i_QPLLCLK=qpll.clk,
                i_QPLLREFCLK=qpll.refclk,
                p_RXOUT_DIV=qpll.Xxout_div,
                i_RXSYSCLKSEL=0b11, # use QPLL & QPLL's REFCLK

                # TX clock
                p_TXBUF_EN="FALSE",
                p_TX_XCLK_SEL="TXUSR",
                o_TXOUTCLK=self.txoutclk,
                i_TXOUTCLKSEL=0b11,

                # TX Startup/Reset
                i_TXPHDLYRESET=0,
                i_TXDLYBYPASS=0,
                i_TXPHALIGNEN=1 if tx_mode in ["master", "slave"] else 0,
                i_GTTXRESET=tx_init.gtXxreset,
                o_TXRESETDONE=tx_init.Xxresetdone,
                i_TXDLYSRESET=tx_init.Xxdlysreset,
                o_TXDLYSRESETDONE=tx_init.Xxdlysresetdone,
                i_TXPHINIT=tx_init.txphinit if tx_mode in ["master", "slave"] else 0,
                o_TXPHINITDONE=tx_init.txphinitdone if tx_mode in ["master", "slave"] else Signal(),
                i_TXPHALIGN=tx_init.Xxphalign if tx_mode in ["master", "slave"] else 0,
                i_TXDLYEN=tx_init.Xxdlyen if tx_mode in ["master", "slave"] else 0,
                o_TXPHALIGNDONE=tx_init.Xxphaligndone,
                i_TXUSERRDY=tx_init.Xxuserrdy,
                p_TXPMARESET_TIME=1,
                p_TXPCSRESET_TIME=1,
                i_TXINHIBIT=~self.tx_enable,

                # TX data
                p_TX_DATA_WIDTH=40,
                p_TX_INT_DATAWIDTH=1, # 1 if a line rate is greater than 6.6 Gbps
                i_TXCHARDISPMODE=Cat(self.txdata[9], self.txdata[19], self.txdata[29], self.txdata[39]),
                i_TXCHARDISPVAL=Cat(self.txdata[8], self.txdata[18], self.txdata[28], self.txdata[38]),
                i_TXDATA=Cat(self.txdata[:8], self.txdata[10:18], self.txdata[20:28], self.txdata[30:38]),
                i_TXUSRCLK=ClockSignal("sys"),
                i_TXUSRCLK2=ClockSignal("sys"),

                # TX electrical
                i_TXBUFDIFFCTRL=0b100,
                i_TXDIFFCTRL=0b1000,

                # RX Startup/Reset
                i_RXPHDLYRESET=0,
                i_RXDLYBYPASS=0,
                i_RXPHALIGNEN=1 if rx_mode in ["master", "slave"] else 0,
                i_GTRXRESET=rx_init.gtXxreset,
                o_RXRESETDONE=rx_init.Xxresetdone,
                i_RXDLYSRESET=rx_init.Xxdlysreset,
                o_RXDLYSRESETDONE=rx_init.Xxdlysresetdone if rx_mode else 0,
                i_RXPHALIGN=rx_init.Xxphalign if rx_mode in ["master", "slave"] else 0,
                i_RXDLYEN=rx_init.Xxdlyen if rx_mode in ["master", "slave"] else 0,
                o_RXPHALIGNDONE=rx_init.Xxphaligndone,
                i_RXUSERRDY=rx_init.Xxuserrdy,
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
                i_RXUSRCLK=ClockSignal("cxp_gt_rx"),
                i_RXUSRCLK2=ClockSignal("cxp_gt_rx"),

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
                i_GTXRXP=pads.rxp,
                i_GTXRXN=pads.rxn,
                o_GTXTXP=pads.txp,
                o_GTXTXN=pads.txn,

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

            self.submodules.comma_aligner = comma_aligner = CommaAligner(0b0101111100)
            self.sync.cxp_gt_rx += [
                comma_aligner.data.eq(rxdata),
                comma_aligner.comma_aligned.eq(comma_aligned),
                comma_aligner.comma_realigned.eq(comma_realigned),
                comma_aligner.comma_det.eq(comma_det),
                comma_aligner_en.eq(comma_aligner.aligner_en),
                self.rx_ready.eq(comma_aligner.ready_sys),
            ]
