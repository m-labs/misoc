from migen import *

from misoc.interconnect.csr import *
from misoc.interconnect.stream import StrideConverter
from misoc.cores.coaxpress.common import char_layout, char_width, word_layout 
from misoc.cores.coaxpress.core.idle import Idle_Word_Inserter
from misoc.cores.coaxpress.core.packet import Command_Test_Packet_Writer, Packet_Wrapper 
from misoc.cores.coaxpress.core.trigger import Trigger_ACK_Inserter, Trigger_Inserter


class HostTXCore(Module, AutoCSR):
    def __init__(self, phy, command_buffer_depth, with_trigger_ack):
        self.trig_stb = Signal()
        self.trig_delay = Signal(char_width)
        self.trig_linktrigger_mode = Signal()

        if with_trigger_ack:
            self.trig_ack_stb = Signal()
        
        # # #
        
        # Host tx pipeline
        #
        #                 32                                                  32            8
        # command/test ───/───> packet ─────> idle word ─────> trigger ack ───/───> conv ───/───> trigger ─────> PHY
        # packet writer         wrapper       inserter         inserter                           inserter
        #                                                      (optional)
        #
        # Equivalent transmission priority:
        # trigger > tigger ack > idle word > command/test packet
        #
        # The pipeline is splited into 32 and 8 bits section to handle the word and char boundary priority insertion requirement:
        # Insertion @ char boundary: trigger packets
        # Insertion @ word boundary: idle packets and trigger ack packet
        # - Section 9.2.4 (CXP-001-2021)
        # 
        # The idle inserter is placed between the trigger ack inserter and command/test packet writer to maintain the trigger performance,
        # as idle word should not be inserted into trigger and trigger ack packet - Section 9.2.5.1 (CXP-001-2021) 
        # 
        

        # Priority level 0 packet - Trigger packet
        self.submodules.trig = trig = Trigger_Inserter()
        self.comb += [
            trig.stb.eq(self.trig_stb),
            trig.delay.eq(self.trig_delay),
            trig.linktrig_mode.eq(self.trig_linktrigger_mode)
        ]

        # Priority level 1 packet - Trigger ack
        if with_trigger_ack:
            self.submodules.trig_ack = trig_ack = Trigger_ACK_Inserter()
            self.comb += self.trig_ack_stb.eq(trig_ack.stb)
        
        # Priority level 2 packet - command and test packet
        # Control is not timing dependent, all the data packets are handled in firmware
        self.submodules.writer = writer = Command_Test_Packet_Writer(command_buffer_depth)

        # writer memory control interface
        self.writer_word_len = CSRStorage(log2_int(command_buffer_depth))
        self.writer_stb = CSR()
        self.writer_stb_testseq = CSR()
        self.writer_busy = CSRStatus()

        self.sync += [
            writer.word_len.eq(self.writer_word_len.storage),
            writer.stb.eq(self.writer_stb.re),
            writer.stb_testseq.eq(self.writer_stb_testseq.re),
            self.writer_busy.status.eq(writer.busy),
        ]

        # Misc
        self.submodules.pak_wrp = pak_wrp = Packet_Wrapper()
        self.submodules.idle = idle = Idle_Word_Inserter()
        self.submodules.converter = converter = StrideConverter(word_layout, char_layout)

        if with_trigger_ack:
            tx_pipeline = [writer, pak_wrp, idle, trig_ack, converter, trig, phy]
        else:
            tx_pipeline = [writer, pak_wrp, idle, converter, trig, phy]

        for s, d in zip(tx_pipeline, tx_pipeline[1:]):
            self.comb += s.source.connect(d.sink)

