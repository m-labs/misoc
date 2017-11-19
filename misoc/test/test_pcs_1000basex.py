import unittest

from migen import *

from misoc.cores.liteeth_mini.phy.pcs_1000basex import *


class TRXPaths(Module):
    def __init__(self):
        self.submodules.tx = TransmitPath()
        self.submodules.rx = ReceivePath()
        self.comb += self.rx.decoder.input.eq(self.tx.encoder.output[0])


class PCSLoopback(Module):
    def __init__(self):
        self.submodules.pcs = ClockDomainsRenamer({"eth_tx": "sys", "eth_rx": "sys"})(
            PCS(check_period=16/125e6, more_ack_time=16/125e6))
        self.comb += self.pcs.tbi_rx.eq(self.pcs.tbi_tx)


class TestPCS(unittest.TestCase):
    def test_trxpaths_config(self):
        config_reg_values = [0x2341, 0x814e, 0x1ea8]

        dut = TRXPaths()

        def send_config_reg():
            yield dut.tx.config_stb.eq(1)
            for value in config_reg_values:
                yield dut.tx.config_reg.eq(value)
                for _ in range(10):
                    yield

        received_config_regs = []
        @passive
        def receive_config_reg():
            while True:
                if (yield dut.rx.seen_config_reg):
                    value = yield dut.rx.config_reg
                    if not received_config_regs or received_config_regs[-1] != value:
                        received_config_regs.append(value)
                yield

        run_simulation(dut, [send_config_reg(), receive_config_reg()])
        self.assertEqual(received_config_regs, config_reg_values)

    def test_trxpaths_data(self):
        ps = [0x55]*7 + [0xd5]
        packets = [ps+[i for i in range(10)],
                   ps+[100+i for i in range(13)],
                   ps+[200+i for i in range(8)]]

        dut = TRXPaths()

        def transmit():
            for packet in packets:
                yield dut.tx.tx_stb.eq(1)
                for byte in packet:
                    yield dut.tx.tx_data.eq(byte)
                    yield
                    while not (yield dut.tx.tx_ack):
                        yield
                yield dut.tx.tx_stb.eq(0)
                for _ in range(12):
                    yield

        received_packets = []
        @passive
        def receive():
            while True:
                while not (yield dut.rx.rx_en):
                    yield
                packet = []
                while (yield dut.rx.rx_en):
                    packet.append((yield dut.rx.rx_data))
                    yield
                received_packets.append(packet)

        run_simulation(dut, [transmit(), receive()])
        self.assertEqual(received_packets, packets)

    def test_pcs(self):
        dut = PCSLoopback()

        def test():
            for i in range(8):
                yield
            link_up = yield dut.pcs.link_up
            self.assertEqual(link_up, 0)
            for i in range(50):
                yield
            link_up = yield dut.pcs.link_up
            self.assertEqual(link_up, 1)

        run_simulation(dut, test())
