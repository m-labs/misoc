from collections import namedtuple

from migen import *
from migen.genlib.fsm import *
from misoc.interconnect import wishbone


__all__ = ["Sequencer",
           "InstEnd", "InstWrite", "InstWait"]


# Instruction set:
#  <2> OP  <1> ADDRESS  <20> DATA_MASK
#
# OP=00: end program, ADDRESS=don't care, DATA_MASK=don't care
# OP=01: write, ADDRESS=address, DATA_MASK=data
# OP=10: wait until masked bits set, ADDRESS=address, DATA_MASK=mask


InstEnd = namedtuple("InstEnd", "")
InstWrite = namedtuple("InstWrite", "address data")
InstWait = namedtuple("InstWait", "address mask")

def encode(inst):
    address, data_mask = 0, 0
    if isinstance(inst, InstEnd):
        opcode = 0b00
    elif isinstance(inst, InstWrite):
        opcode = 0b01
        address = inst.address
        data_mask = inst.data
    elif isinstance(inst, InstWait):
        opcode = 0b10
        address = inst.address
        data_mask = inst.mask
    else:
        raise ValueError
    return (opcode << 21) | (address << 20) | data_mask


class Sequencer(Module):
    def __init__(self, program, bus=None):
        if bus is None:
            bus = wishbone.Interface()
        self.bus = bus

        ###

        assert isinstance(program[-1], InstEnd)
        program_e = [encode(inst) for inst in program]
        mem = Memory(32, len(program), init=program_e)
        self.specials += mem

        mem_port = mem.get_port()
        self.specials += mem_port

        fsm = FSM(reset_state="FETCH")
        self.submodules += fsm

        i_opcode = mem_port.dat_r[21:23]
        i_address = mem_port.dat_r[20:21]
        i_data_mask = mem_port.dat_r[0:20]

        self.sync += [
            self.bus.adr.eq(i_address),
            self.bus.sel.eq(1),
            self.bus.dat_w.eq(i_data_mask),
        ]

        fsm.act("FETCH", NextState("DECODE"))
        fsm.act("DECODE",
            If(i_opcode == 0b00,
                NextState("END")
            ).Elif(i_opcode == 0b01,
                NextState("WRITE")
            ).Elif(i_opcode == 0b10,
                NextState("WAIT")
            )
        )
        fsm.act("WRITE",
            self.bus.cyc.eq(1),
            self.bus.stb.eq(1),
            self.bus.we.eq(1),
            If(self.bus.ack,
                NextValue(mem_port.adr, mem_port.adr + 1),
                NextState("FETCH")
            )
        )
        fsm.act("WAIT",
            self.bus.cyc.eq(1),
            self.bus.stb.eq(1),
            If(self.bus.ack & ((self.bus.dat_r & i_data_mask) == i_data_mask),
                NextValue(mem_port.adr, mem_port.adr + 1),
                NextState("FETCH")
            )
        )
        fsm.act("END", NextState("END"))
