from migen import *

from misoc.cores.coaxpress.common import (
    char_width,
    KCode,
    switch_endianness,
    word_layout,
    word_layout_dchar,
    word_width,
)
from misoc.interconnect.stream import Endpoint

class Packet_Wrapper(Module):
    def __init__(self):
        self.sink = Endpoint(word_layout)
        self.source = Endpoint(word_layout)

        # # #

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        
        fsm.act("IDLE",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                self.sink.ack.eq(0),
                NextState("INSERT_HEADER"),
            )
        )

        fsm.act("INSERT_HEADER",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(KCode["pak_start"], 4)),
            self.source.k.eq(Replicate(1, 4)),
            If(self.source.ack, NextState("COPY")),
        )

        fsm.act("COPY",
            self.sink.connect(self.source),
            self.source.eop.eq(0),
            If(self.sink.stb & self.sink.eop & self.source.ack,
                NextState("INSERT_FOOTER"),
            ),
        )

        fsm.act("INSERT_FOOTER",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(KCode["pak_end"], 4)),
            self.source.k.eq(Replicate(1, 4)),
            self.source.eop.eq(1),
            If(self.source.ack, NextState("IDLE")),
        )


@FullMemoryWE()
class Command_Test_Packet_Writer(Module):
    def __init__(self, buffer_depth):
        self.word_len = Signal(log2_int(buffer_depth))
        self.stb = Signal()
        self.stb_testseq = Signal()

        self.busy = Signal()

        # # #
        
        self.specials.mem = mem = Memory(word_width, buffer_depth)
        self.specials.mem_port = mem_port = mem.get_port()
        self.source = Endpoint(word_layout)

        # increment addr in the same cycle the moment addr_inc is high
        # as memory takes one cycle to shift to the correct addr
        addr_next = Signal(log2_int(buffer_depth))
        addr = Signal.like(addr_next)
        addr_rst = Signal()
        addr_inc = Signal()
        self.sync += addr.eq(addr_next),

        self.comb += [
            addr_next.eq(addr),
            If(addr_rst,
                addr_next.eq(addr_next.reset),
            ).Elif(addr_inc,
                addr_next.eq(addr + 1),
            ),
            mem_port.adr.eq(addr_next),
        ]

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        self.comb += self.busy.eq(~fsm.ongoing("IDLE"))

        cnt = Signal(max=0xFFF)
        fsm.act("IDLE",
            addr_rst.eq(1),
            If(self.stb, NextState("TRANSMIT")),
            If(self.stb_testseq, 
                NextValue(cnt, cnt.reset),
                NextState("WRITE_TEST_PACKET_TYPE"),
            )
        )

        fsm.act("TRANSMIT",
            self.source.stb.eq(1),
            self.source.data.eq(mem_port.dat_r),
            If(self.source.ack,
                addr_inc.eq(1),
            ),
            If(addr_next == self.word_len,
                self.source.eop.eq(1),
                NextState("IDLE")
            )
        )

        fsm.act("WRITE_TEST_PACKET_TYPE",
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(C(0x04, char_width), 4)),
            self.source.k.eq(Replicate(0, 4)),
            If(self.source.ack,NextState("WRITE_TEST_COUNTER"))
        )

        fsm.act("WRITE_TEST_COUNTER",
            self.source.stb.eq(1),
            self.source.data[:8].eq(cnt[:8]),
            self.source.data[8:16].eq(cnt[:8]+1),
            self.source.data[16:24].eq(cnt[:8]+2),
            self.source.data[24:].eq(cnt[:8]+3),
            self.source.k.eq(Cat(0, 0, 0, 0)),
            If(self.source.ack,
                If(cnt == 0xFFC,
                    self.source.eop.eq(1),
                    NextState("IDLE")
                ).Else(
                    NextValue(cnt, cnt + 4),
                )
               
            )
        )


class Packet_Arbiter(Module):
    def __init__(self):
        self.decode_err = Signal()
        self.recv_test_pak = Signal()
        self.recv_heartbeat = Signal()

        self.sink = Endpoint(word_layout_dchar)
        self.source_stream = Endpoint(word_layout_dchar)
        self.source_test = Endpoint(word_layout_dchar)
        self.source_heartbeat = Endpoint(word_layout_dchar)
        self.source_command = Endpoint(word_layout_dchar)

        # # #

        type = {
            "data_stream": 0x01,
            "control_ack_no_tag": 0x03,
            "test_packet": 0x04,
            "control_ack_with_tag": 0x06,
            "event": 0x07,
            "heartbeat": 0x09,
        }


        # Data packet parser
        self.submodules.fsm = fsm = FSM(reset_state="IDLE")

        fsm.act("IDLE",
            self.sink.ack.eq(1),
            If((self.sink.stb & (self.sink.dchar == KCode["pak_start"]) & (self.sink.dchar_k == 1)),
                NextState("DECODE"),
            )
        )

        fsm.act("DECODE",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                Case(self.sink.dchar, {
                    type["data_stream"]: NextState("COPY_STREAM_PACKET"),
                    type["test_packet"]: [
                        self.recv_test_pak.eq(1),
                        NextState("COPY_TEST_PACKET"),
                    ],
                    type["control_ack_no_tag"]:[
                        # pass packet type for downstream modules
                        self.source_command.stb.eq(1),
                        self.source_command.data.eq(self.sink.data),
                        NextState("COPY_COMMAND_PACKET"),
                    ],
                    type["control_ack_with_tag"]:[
                        # pass packet type for downstream modules
                        self.source_command.stb.eq(1),
                        self.source_command.data.eq(self.sink.data),
                        NextState("COPY_COMMAND_PACKET"),
                    ],
                    type["event"]: [
                        # pass packet type for downstream modules 
                        self.source_command.stb.eq(1),
                        self.source_command.data.eq(self.sink.data),
                        NextState("COPY_COMMAND_PACKET"),
                    ],
                    type["heartbeat"] : [
                        self.recv_heartbeat.eq(1),
                         NextState("COPY_HEARTBEAT_PACKET"),
                    ],
                    "default": [
                         self.decode_err.eq(1),
                         # wait till next valid packet
                         NextState("IDLE"),
                    ],
                }),
            )
        )

        # copy stream data packet with K29.7 
        fsm.act("COPY_STREAM_PACKET",
            self.sink.connect(self.source_stream),
            If((self.sink.stb & self.source_stream.ack & (self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                NextState("IDLE")
            )      
        )

        # copy test sequence packet with K29.7 
        fsm.act("COPY_TEST_PACKET",
            self.sink.connect(self.source_test),
            If((self.sink.stb & self.source_test.ack & (self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                NextState("IDLE")
            )      
        )

        # copy command packet with K29.7 
        fsm.act("COPY_COMMAND_PACKET",
            self.sink.connect(self.source_command),
            If((self.sink.stb & self.source_command.ack & (self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                NextState("IDLE")
            )      
        )

        # copy heartbeat packet with K29.7 
        fsm.act("COPY_HEARTBEAT_PACKET",
            self.sink.connect(self.source_heartbeat),
            If((self.sink.stb & self.source_heartbeat.ack & (self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                NextState("IDLE")
            )      
        )


@FullMemoryWE()
class Command_Packet_Reader(Module):
    def __init__(self, buffer_depth, nslot):
        self.write_ptr = Signal(log2_int(nslot))
        self.read_ptr = Signal.like(self.write_ptr)
        self.buffer_err = Signal()

        self.sink = Endpoint(word_layout_dchar)

        # # #
         
        # N buffers for firmware to read packet from
         
        self.specials.mem = mem = Memory(word_width, nslot*buffer_depth)
        self.specials.mem_port = mem_port = mem.get_port(write_capable=True)
        buf_mem_we = Signal.like(mem_port.we)
        buf_mem_dat_w = Signal.like(mem_port.dat_w)
        buf_mem_adr = Signal.like(mem_port.adr)

        # buffered mem_port to improve timing
        self.sync += [
            mem_port.we.eq(buf_mem_we),
            mem_port.dat_w.eq(buf_mem_dat_w),
            mem_port.adr.eq(buf_mem_adr)
        ]

        addr_nbits = log2_int(buffer_depth)
        addr = Signal(addr_nbits)
        self.comb += [
            buf_mem_adr[:addr_nbits].eq(addr),
            buf_mem_adr[addr_nbits:].eq(self.write_ptr),
        ]

        # Data packet parser
        self.submodules.fsm = fsm = FSM(reset_state="LOAD_BUFFER")

        fsm.act("LOAD_BUFFER",
            buf_mem_we.eq(0),
            self.sink.ack.eq(1),
            If(self.sink.stb,
                If(((self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                    NextState("MOVE_BUFFER_PTR"),
                ).Else(
                    buf_mem_we.eq(1),
                    buf_mem_dat_w.eq(self.sink.data),
                    NextValue(addr, addr + 1),
                    If(addr == buffer_depth - 1,
                        # discard the packet
                        self.buffer_err.eq(1),
                        NextValue(addr, addr.reset),
                    )
                )
            )
        )

        fsm.act("MOVE_BUFFER_PTR",
            self.sink.ack.eq(0),
            If(self.write_ptr + 1 == self.read_ptr,
                # if next one hasn't been read, overwrite the current buffer when new packet comes in
                self.buffer_err.eq(1),
            ).Else(
                NextValue(self.write_ptr, self.write_ptr + 1),
            ),
            NextValue(addr, addr.reset),
            NextState("LOAD_BUFFER"),
        )


class Heartbeat_Packet_Reader(Module):
    def __init__(self):
        self.host_id = Signal(4*char_width)
        self.heartbeat = Signal(8*char_width)

        self.sink = Endpoint(word_layout_dchar)

        # # #

        n_chars = 12
        packet_layout = [
            ("stream_id", len(self.host_id)),
            ("source_tag", len(self.heartbeat)), 
        ]
        assert layout_len(packet_layout) == n_chars*char_width  


        cnt = Signal(max=n_chars)
        packet_buffer = Signal(layout_len(packet_layout))
        case = dict(
            (i, packet_buffer[8*i:8*(i+1)].eq(self.sink.dchar))
            for i in range(n_chars)
        )
        self.sync += [
            self.host_id.eq(switch_endianness(packet_buffer[:4*char_width])),
            self.heartbeat.eq(switch_endianness(packet_buffer[4*char_width:])),

            self.sink.ack.eq(1),
            If(self.sink.stb,
                Case(cnt, case),
                If(((self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                    cnt.eq(cnt.reset),
                ).Else(
                    cnt.eq(cnt + 1),
                ),
            ),
        ]
        

class Test_Sequence_Checker(Module):
    def __init__(self):
        self.error = Signal()

        self.sink = Endpoint(word_layout_dchar)

        # # #

        # Section 9.9.1 (CXP-001-2021)
        # the received test data packet (0x00, 0x01 ... 0xFF) 
        # need to be compared against the local test sequence generator
        cnt_bytes = [Signal(char_width, reset=i) for i in range(4)]
        test_errors = [Signal() for _ in range(4)]

        self.sync += [
            self.sink.ack.eq(1),
            self.error.eq(reduce(or_, test_errors))
        ]
        for i, (cnt, err) in enumerate(zip(cnt_bytes,test_errors)):
            self.sync += [
                err.eq(0),
                If(self.sink.stb,
                    If(((self.sink.dchar == KCode["pak_end"]) & (self.sink.dchar_k == 1)),
                        cnt.eq(cnt.reset)
                    ).Else(
                        If(self.sink.data[8 * i : 8 * (i + 1)] != cnt,
                            err.eq(1),
                        ),
                        If(cnt == 0xFC + i,
                            cnt.eq(cnt.reset),
                        ).Else(
                            cnt.eq(cnt + 4)
                        ),
                    )
                )
            ]

