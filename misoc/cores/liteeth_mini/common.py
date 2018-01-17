from migen import *

eth_mtu = 1530
eth_min_len = 46
eth_interpacket_gap = 12
eth_preamble = 0xD555555555555555


def eth_phy_layout(dw=8):
    return [
        ("data", dw),
        ("last_be", dw//8),
        ("error", dw//8)
    ]
