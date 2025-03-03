from migen import *

from misoc.cores.coaxpress.common import word_layout, word_layout_dchar
from misoc.interconnect.stream import Endpoint

from functools import reduce
from itertools import combinations
from operator import or_, and_


class DuplicatedCharDecoder(Module):
    def __init__(self):
        self.sink = Endpoint(word_layout)
        self.source = Endpoint(word_layout_dchar)

        # # #

        # For duplicated characters, an error correction method (e.g. majority voting) is required to meet the CXP spec:
        # RX decoder should immune to single bit errors when handling duplicated characters - Section 9.2.2.1 (CXP-001-2021)
        #
        #
        #                               32
        #             ┌───>  buffer  ───/───┐
        #         32  │                     │   40
        # sink ───/───┤                 8   ├───/───> source
        #             │              (dchar)│
        #             └───> majority ───/───┘
        #                   voting
        #
        #
        # Due to the tight setup/hold time requiremnt for 12.5Gbps CXP, the voting logic cannot be implemented as combinational logic
        # Hence, a pipeline approach is needed to avoid any s/h violation, where the majority voting result are pre-calculate and injected into the bus immediate after the PHY.
        # And any downstream modules can access the voting result anytime

        # cycle 1 - buffer data & calculate intermediate result
        buffer = Endpoint(word_layout)
        self.sync += [
            If(buffer.ack,
                self.sink.connect(buffer, omit={"ack"}),
            )
        ]
        self.comb += self.sink.ack.eq(buffer.ack)

        # calculate ABC, ABD, ACD, BCD
        chars = [{"data": self.sink.data[i * 8 : (i + 1) * 8], "k": self.sink.k[i]} for i in range(4)]
        voters = [Record([("data", 8), ("k", 1)]) for _ in range(4)]

        for i, comb in enumerate(combinations(chars, 3)):
            self.sync += [
                If(buffer.ack,
                    voters[i].data.eq(reduce(and_, [char["data"] for char in comb])),
                    voters[i].k.eq(reduce(and_, [char["k"] for char in comb])),
                )
            ]

        # cycle 2 - inject the voting result
        self.sync += [
            If(self.source.ack,
                buffer.connect(self.source, omit={"ack", "dchar", "dchar_k"}),
                self.source.dchar.eq(Replicate(reduce(or_, [v.data for v in voters]), 4)),
                self.source.dchar_k.eq(Replicate(reduce(or_, [v.k for v in voters]), 4)),
            )
        ]
        self.comb += buffer.ack.eq(self.source.ack)
