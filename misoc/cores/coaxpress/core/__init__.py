from migen import *
from migen.genlib.cdc import MultiReg, PulseSynchronizer

from misoc.interconnect.csr import *
from misoc.interconnect.stream import Buffer, StrideConverter
from misoc.cores.coaxpress.common import (
    char_layout,
    char_width,
    word_layout,
    word_layout_dchar,
)
from misoc.cores.coaxpress.core.dchar import DuplicatedCharDecoder
from misoc.cores.coaxpress.core.idle import IdleWordInserter
from misoc.cores.coaxpress.core.packet import (
    CommandPacketReader,
    CommandTestPacketWriter,
    HeartbeatPacketReader,
    PacketArbiter,
    PacketWrapper,
    TestSequenceChecker,
)
from misoc.cores.coaxpress.core.trigger import (
    TriggerACKInserter,
    TriggerACKReader,
    TriggerInserter,
    TriggerReader,
)


class HostTXCore(Module, AutoCSR):
    def __init__(self, phy, command_buffer_depth, clk_freq, with_trigger_ack):
        self.trig_stb = Signal()
        self.trig_linktrig_mode = Signal(2)
        self.trig_extra_linktrig = Signal()

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
        self.submodules.trig = trig = TriggerInserter(clk_freq)
        self.comb += [
            trig.stb.eq(self.trig_stb),
            trig.linktrig_mode.eq(self.trig_linktrig_mode),
            trig.extra_linktrig.eq(self.trig_extra_linktrig),
            trig.bitrate2x.eq(phy.bitrate2x_enable)
        ]

        # Priority level 1 packet - Trigger ack
        if with_trigger_ack:
            self.submodules.trig_ack = trig_ack = TriggerACKInserter()
            self.comb += self.trig_ack_stb.eq(trig_ack.stb)
        
        # Priority level 2 packet - command and test packet
        # Control is not timing dependent, all the data packets are handled in firmware
        self.submodules.writer = writer = CommandTestPacketWriter(command_buffer_depth)

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
        self.submodules.pak_wrp = pak_wrp = PacketWrapper()
        self.submodules.idle = idle = IdleWordInserter()
        self.submodules.converter = converter = StrideConverter(word_layout, char_layout)

        if with_trigger_ack:
            tx_pipeline = [writer, pak_wrp, idle, trig_ack, converter, trig, phy]
        else:
            tx_pipeline = [writer, pak_wrp, idle, converter, trig, phy]

        for s, d in zip(tx_pipeline, tx_pipeline[1:]):
            self.comb += s.source.connect(d.sink)


class HostRXCore(Module, AutoCSR):
    def __init__(self, phy, command_buffer_depth, nslot, with_trigger):
        self.ready = CSRStatus()

        self.trigger_ack = CSR()

        self.pending_packet = CSR()
        self.read_ptr = CSRStatus(log2_int(nslot))
        self.reader_buffer_err = CSR()

        self.reader_decode_err = CSR()
        self.test_error_counter = CSRStatus(16)
        self.test_packet_counter = CSRStatus(16)
        self.test_counts_reset = CSR()

        self.heartbeat = CSR()
        self.host_id = CSRStatus(32)
        self.device_time = CSRStatus(64)

        if with_trigger:
            self.trig = Signal()
            self.trig_delay = Signal(char_width)
            self.trig_linktrigger_n = Signal(char_width)
        
        # # #

        gtx = phy.gtx
        self.sync += self.ready.status.eq(gtx.rx_ready),

        # Host rx pipeline 
        #
        #        32             32+8(dchar)
        # PHY ───/───> dchar   ─────/─────> trigger  ─────> trigger ack  ─────> buffer ─────>  packet arbiter ─────> stream packet with K29.7
        #              decoder              reader          reader                                    │  │  │ 
        #                                 (optional)                                                  │  │  └──────> test sequence checker
        #                                                                                             │  │
        #                                                                                             │  └─────────> heartbeat packet reader
        #                                                                                             │   
        #                                                                                             └────────────> command packet reader
        #  
        cdr = ClockDomainsRenamer("cxp_gt_rx")

        # decode all incoming data as duplicate char and inject the result into the bus for downstream modules
        self.submodules.dchar_decoder = dchar_decoder = cdr(DuplicatedCharDecoder())

        # Priority level 0 packet - Trigger packet
        if with_trigger:
            self.submodules.trig_reader = trig_reader = cdr(TriggerReader())
            self.sync.cxp_gt_rx += [
                self.trig.eq(trig_reader.trig),
                self.trig_delay.eq(trig_reader.delay),
                self.trig_linktrigger_n.eq(trig_reader.linktrigger_n),
            ]

        # Priority level 1 packet - Trigger ack packet
        self.submodules.trig_ack_reader= trig_ack_reader = cdr(TriggerACKReader())
        
        self.submodules.trig_ack_ps = trig_ack_ps = PulseSynchronizer("cxp_gt_rx", "sys")
        self.sync.cxp_gt_rx += trig_ack_ps.i.eq(trig_ack_reader.ack)
        self.sync += [
            If(trig_ack_ps.o,
                self.trigger_ack.w.eq(1),
            ).Elif(self.trigger_ack.re,
                self.trigger_ack.w.eq(0),
            ),
        ]

        # Priority level 2 packet - stream, test, heartbeat and command packets
        self.submodules.arbiter = arbiter = cdr(PacketArbiter())

        self.submodules.decode_err_ps = decode_err_ps = PulseSynchronizer("cxp_gt_rx", "sys")
        self.sync.cxp_gt_rx += decode_err_ps.i.eq(arbiter.decode_err)
        self.sync += [
            If(decode_err_ps.o,
                self.reader_decode_err.w.eq(1),
            ).Elif(self.reader_decode_err.re,
                self.reader_decode_err.w.eq(0),
            ),
        ]

        # Buffer to improve timing
        self.submodules.buffer = buffer = cdr(Buffer(word_layout_dchar))

        if with_trigger:
            rx_pipeline = [phy, dchar_decoder, trig_reader, trig_ack_reader, buffer, arbiter]
        else:
            rx_pipeline = [phy, dchar_decoder, trig_ack_reader, buffer, arbiter]
        for s, d in zip(rx_pipeline, rx_pipeline[1:]):
            self.comb += s.source.connect(d.sink)

        # Stream packet
        # set pipeline source to output stream packet 
        self.source = arbiter.source_stream

        # Test packet 
        self.submodules.test_seq_checker = test_seq_checker = cdr(TestSequenceChecker())
        self.comb += arbiter.source_test.connect(test_seq_checker.sink)
        
        self.submodules.test_reset_ps = test_reset_ps = PulseSynchronizer("sys", "cxp_gt_rx")
        self.comb += test_reset_ps.i.eq(self.test_counts_reset.re),

        test_err_cnt_rx = Signal.like(self.test_error_counter.status)
        test_pak_cnt_rx = Signal.like(self.test_packet_counter.status)
        test_err_r, test_pak_r = Signal(), Signal()
        self.sync.cxp_gt_rx += [ 
            test_err_r.eq(test_seq_checker.error),
            test_pak_r.eq(arbiter.recv_test_pak),

            If(test_reset_ps.o,
                test_err_cnt_rx.eq(test_err_cnt_rx.reset),
            ).Elif(test_err_r,
                test_err_cnt_rx.eq(test_err_cnt_rx + 1),
            ),
            If(test_reset_ps.o,
                test_pak_cnt_rx.eq(test_pak_cnt_rx.reset),
            ).Elif(test_pak_r,
                test_pak_cnt_rx.eq(test_pak_cnt_rx + 1),
            ),
        ]
        self.specials += [
            MultiReg(test_err_cnt_rx, self.test_error_counter.status),
            MultiReg(test_pak_cnt_rx, self.test_packet_counter.status),
        ]

        # Command packet
        self.submodules.command_reader = command_reader = cdr(CommandPacketReader(command_buffer_depth, nslot))
        self.comb += arbiter.source_command.connect(command_reader.sink)

        # nslot buffers control interface
        write_ptr_sys = Signal.like(command_reader.write_ptr)
        
        self.specials += [
            MultiReg(self.read_ptr.status, command_reader.read_ptr, odomain="cxp_gt_rx"),
            MultiReg(command_reader.write_ptr, write_ptr_sys)
        ]
        self.sync += [
            self.pending_packet.w.eq(self.read_ptr.status != write_ptr_sys),
            If(~gtx.rx_ready,
                self.read_ptr.status.eq(0),
            ).Elif(self.pending_packet.re & self.pending_packet.w, 
                self.read_ptr.status.eq(self.read_ptr.status + 1),
            )
        ]

        self.submodules.buffer_err_ps = buffer_err_ps = PulseSynchronizer("cxp_gt_rx", "sys")
        self.sync.cxp_gt_rx += buffer_err_ps.i.eq(command_reader.buffer_err),
        self.sync += [
            If(buffer_err_ps.o,
                self.reader_buffer_err.w.eq(1),
            ).Elif(self.reader_buffer_err.re,
                self.reader_buffer_err.w.eq(0),
            ),
        ]

        # Heartbeat packet
        self.submodules.heartbeat_reader = heartbeat_reader = cdr(HeartbeatPacketReader())
        self.comb += arbiter.source_heartbeat.connect(heartbeat_reader.sink)

        self.specials += [
            MultiReg(heartbeat_reader.host_id, self.host_id.status),
            MultiReg(heartbeat_reader.heartbeat, self.device_time.status),
        ]
        
        self.submodules.heartbeat_ps = heartbeat_ps = PulseSynchronizer("cxp_gt_rx", "sys")
        self.sync.cxp_gt_rx += heartbeat_ps.i.eq(arbiter.recv_heartbeat)
        self.sync += [
            If(heartbeat_ps.o,
                self.heartbeat.w.eq(1),
            ).Elif(self.heartbeat.re,
                self.heartbeat.w.eq(0),
            ),
        ]
