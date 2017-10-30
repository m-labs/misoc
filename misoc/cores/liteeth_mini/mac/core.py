from migen import *
from migen.genlib.cdc import PulseSynchronizer

from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import *
from misoc.cores.liteeth_mini.mac import gap, preamble, crc, padding, last_be


class LiteEthMACCore(Module, AutoCSR):
    def __init__(self, phy, dw, endianness="big",
            with_preamble_crc=True,
            with_padding=True):
        if dw < phy.dw:
            raise ValueError("Core data width({}) must be larger than PHY data width({})".format(dw, phy.dw))

        rx_pipeline = [phy]
        tx_pipeline = [phy]

        # Interpacket gap
        tx_gap_inserter = gap.LiteEthMACGap(phy.dw)
        rx_gap_checker = gap.LiteEthMACGap(phy.dw, ack_on_gap=True)
        self.submodules += ClockDomainsRenamer("eth_tx")(tx_gap_inserter)
        self.submodules += ClockDomainsRenamer("eth_rx")(rx_gap_checker)

        tx_pipeline += [tx_gap_inserter]
        rx_pipeline += [rx_gap_checker]

        # Preamble / CRC
        if with_preamble_crc:
            self._preamble_crc = CSRStatus(reset=1)
            self.crc_errors = CSRStatus(32)

            # Preamble insert/check
            preamble_inserter = preamble.LiteEthMACPreambleInserter(phy.dw)
            preamble_checker = preamble.LiteEthMACPreambleChecker(phy.dw)
            self.submodules += ClockDomainsRenamer("eth_tx")(preamble_inserter)
            self.submodules += ClockDomainsRenamer("eth_rx")(preamble_checker)

            # CRC insert/check
            crc32_inserter = crc.LiteEthMACCRC32Inserter(eth_phy_layout(phy.dw))
            crc32_checker = crc.LiteEthMACCRC32Checker(eth_phy_layout(phy.dw))
            self.submodules += ClockDomainsRenamer("eth_tx")(crc32_inserter)
            self.submodules += ClockDomainsRenamer("eth_rx")(crc32_checker)

            tx_pipeline += [preamble_inserter, crc32_inserter]
            rx_pipeline += [preamble_checker, crc32_checker]

            # CRC error counter
            self.submodules.ps_crc_error = PulseSynchronizer("eth_rx", "sys")

            self.comb += self.ps_crc_error.i.eq(crc32_checker.crc_error)
            self.sync += [
                If(self.ps_crc_error.o,
                    self.crc_errors.status.eq(self.crc_errors.status + 1))]

        # Padding
        if with_padding:
            padding_inserter = padding.LiteEthMACPaddingInserter(phy.dw, 60)
            padding_checker = padding.LiteEthMACPaddingChecker(phy.dw, 60)
            self.submodules += ClockDomainsRenamer("eth_tx")(padding_inserter)
            self.submodules += ClockDomainsRenamer("eth_rx")(padding_checker)

            tx_pipeline += [padding_inserter]
            rx_pipeline += [padding_checker]

        # Delimiters
        if dw != 8:
            tx_last_be = last_be.LiteEthMACTXLastBE(phy.dw)
            rx_last_be = last_be.LiteEthMACRXLastBE(phy.dw)
            self.submodules += ClockDomainsRenamer("eth_tx")(tx_last_be)
            self.submodules += ClockDomainsRenamer("eth_rx")(rx_last_be)

            tx_pipeline += [tx_last_be]
            rx_pipeline += [rx_last_be]

        # Converters
        if dw != phy.dw:
            reverse = endianness == "big"
            tx_converter = stream.StrideConverter(eth_phy_layout(dw),
                                     eth_phy_layout(phy.dw),
                                     reverse=reverse)
            rx_converter = stream.StrideConverter(eth_phy_layout(phy.dw),
                                     eth_phy_layout(dw),
                                     reverse=reverse)
            self.submodules += ClockDomainsRenamer("eth_tx")(tx_converter)
            self.submodules += ClockDomainsRenamer("eth_rx")(rx_converter)

            tx_pipeline += [tx_converter]
            rx_pipeline += [rx_converter]

        # Cross Domain Crossing
        tx_cdc = stream.AsyncFIFO(eth_phy_layout(dw), 64)
        rx_cdc = stream.AsyncFIFO(eth_phy_layout(dw), 64)
        self.submodules += ClockDomainsRenamer({"write": "sys", "read": "eth_tx"})(tx_cdc)
        self.submodules += ClockDomainsRenamer({"write": "eth_rx", "read": "sys"})(rx_cdc)

        tx_pipeline += [tx_cdc]
        rx_pipeline += [rx_cdc]

        tx_pipeline_r = list(reversed(tx_pipeline))
        for s, d in zip(tx_pipeline_r, tx_pipeline_r[1:]):
            self.comb += s.source.connect(d.sink)
        for s, d in zip(rx_pipeline, rx_pipeline[1:]):
            self.comb += s.source.connect(d.sink)
        self.sink = tx_pipeline[-1].sink
        self.source = rx_pipeline[-1].source
