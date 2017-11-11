from migen import *
from migen.genlib.fsm import *

from misoc.cores import code_8b10b


def K(x, y):
    return (y << 5) | x


def D(x, y):
    return (y << 5) | x


class TransmitPath(Module):
    def __init__(self, lsb_first=False):
        self.config_stb = Signal()
        self.config_reg = Signal(16)
        self.tx_stb = Signal()
        self.tx_ack = Signal()
        self.tx_data = Signal(8)

        self.submodules.encoder = code_8b10b.Encoder(lsb_first=lsb_first)

        # # #

        parity = Signal()
        c_type = Signal()
        self.sync += parity.eq(~parity)

        fsm = FSM()
        self.submodules += fsm

        fsm.act("START",
            If(self.config_stb,
                self.encoder.k[0].eq(1),
                self.encoder.d[0].eq(K(28, 5)),
                NextState("CONFIG_D")
            ).Else(
                self.tx_ack.eq(1),
                If(self.tx_stb,
                    # the first byte of the preamble is replaced by /S/
                    self.encoder.k[0].eq(1),
                    self.encoder.d[0].eq(K(27, 7)),
                    NextState("DATA")
                ).Else(
                    self.encoder.k[0].eq(1),
                    self.encoder.d[0].eq(K(28, 5)),
                    NextState("IDLE")
                )
            )
        )
        fsm.act("CONFIG_D",
            If(c_type,
                self.encoder.d[0].eq(D(2, 2))
            ).Else(
                self.encoder.d[0].eq(D(21, 5))
            ),
            NextValue(c_type, ~c_type),
            NextState("CONFIG_REG_LSB")
        ),
        fsm.act("CONFIG_REG_LSB",
            self.encoder.d[0].eq(self.config_reg[:8]),
            NextState("CONFIG_REG_MSB")
        )
        fsm.act("CONFIG_REG_MSB",
            self.encoder.d[0].eq(self.config_reg[8:]),
            NextState("START")
        )
        fsm.act("IDLE",
            # due to latency in the encoder, we read here the disparity
            # just before the K28.5 was sent. K28.5 flips the disparity.
            If(self.encoder.disparity[0],
                # correcting /I1/ (D5.6 preserves the disparity)
                self.encoder.d[0].eq(D(5, 6))
            ).Else(
                # preserving /I2/ (D16.2 flips the disparity)
                self.encoder.d[0].eq(D(16, 2))
            ),
            NextState("START")
        )
        fsm.act("DATA",
            self.tx_ack.eq(1),
            If(self.tx_stb,
                self.encoder.d[0].eq(self.tx_data)
            ).Else(
                # /T/
                self.encoder.k[0].eq(1),
                self.encoder.d[0].eq(K(29, 7)),
                NextState("CARRIER_EXTEND_1")
            )
        )
        fsm.act("CARRIER_EXTEND_1",
            # /R/
            self.encoder.k[0].eq(1),
            self.encoder.d[0].eq(K(23, 7)),
            If(parity,
                NextState("START")
            ).Else(
                NextState("CARRIER_EXTEND_2")
            )
        )
        fsm.act("CARRIER_EXTEND_2",
            # /R/
            self.encoder.k[0].eq(1),
            self.encoder.d[0].eq(K(23, 7)),
            NextState("START")
        )
