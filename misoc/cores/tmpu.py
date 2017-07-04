"""
Trivial memory protection unit.

Memory is divided into "pages" of 2**page_bits words.

Bus errors are generated in two cases:
  * accesses within page 0 (to help catch NULL pointers dereferences)
  * accesses within a programmable page (to implement stack probing)

To avoid a delay of one cycle, the transaction is sent immediately to the
output bus. Thus, bus cycles are not aborted, in particular write transactions
will be executed even if they trigger the protection. Stack probing should use
read transactions for this reason.

This module must not be used with Wishbone combinatorial feedback (slaves may
not ack transactions in the same cycle as they are issued).

All sizes/addresses in bytes.
"""

from migen import *

from misoc.interconnect import wishbone
from misoc.interconnect.csr import *


class TMPU(Module, AutoCSR):
    def __init__(self, input_bus, page_size=4096):
        self.output_bus = wishbone.Interface.like(input_bus)

        word_bits = log2_int(len(input_bus.dat_w)//8)
        page_bits = log2_int(page_size) - word_bits

        self.page_size = CSRConstant(page_size)
        self.enable_null = CSRStorage()
        self.enable_prog = CSRStorage()
        self.prog_address = CSRStorage(len(input_bus.adr),
                                       alignment_bits=word_bits+page_bits)

        # # #

        error = Signal()
        page = input_bus.adr[page_bits:]
        self.sync += [
            error.eq(0),
            If(self.enable_null.storage &
               (page == 0), error.eq(1)),
            If(self.enable_prog.storage &
               (page == self.prog_address.storage), error.eq(1))
        ]
        self.comb += [
            input_bus.connect(self.output_bus, omit={"ack", "err"}),
            If(error,
                input_bus.ack.eq(0),
                input_bus.err.eq(self.output_bus.ack | self.output_bus.err)
            ).Else(
                input_bus.ack.eq(self.output_bus.ack),
                input_bus.err.eq(self.output_bus.err)
            )
        ]
