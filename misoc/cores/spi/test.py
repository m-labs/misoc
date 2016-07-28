from migen import *

from itertools import product
from misoc.cores.spi import SPIMaster
from misoc.interconnect.csr_bus import *


(
    SPI_DATA_READ,
    SPI_DATA_WRITE,
    SPI_XFER_LEN_READ,
    SPI_XFER_LEN_WRITE,
    SPI_SEL,
    SPI_OFFLINE,
    SPI_CS_POLARITY,
    SPI_CLK_POLARITY,
    SPI_CLK_PHASE,
    SPI_LSB_FIRST,
    SPI_HALF_DUPLEX,
    SPI_ACTIVE,
    SPI_PENDING,
    SPI_CLK_DIV_READ,
    SPI_CLK_DIV_WRITE
) = (0, 4) + tuple(i for i in range(8, 21))


def _test_xfer(bus, cs, wlen, rlen, wdata):
    yield from bus.write(SPI_XFER_LEN_READ, rlen)
    yield from bus.write(SPI_XFER_LEN_WRITE, wlen)
    yield from bus.write(SPI_SEL, cs & 0xFF)

    yield from bus.write(SPI_DATA_WRITE, (wdata >> 24) & 0xFF)
    yield from bus.write(SPI_DATA_WRITE + 1, (wdata >> 16) & 0xFF)
    yield from bus.write(SPI_DATA_WRITE + 2, (wdata >> 8) & 0xFF)
    yield from bus.write(SPI_DATA_WRITE + 3, wdata & 0xFF)
    yield


def _read_data(bus):
    return ((yield from bus.read(SPI_DATA_READ)) << 24 |
            (yield from bus.read(SPI_DATA_READ + 1)) << 16 |
            (yield from bus.read(SPI_DATA_READ + 2)) << 8 |
            (yield from bus.read(SPI_DATA_READ + 3)))


def _test_read(bus):
    # Order matters: Check SPI_PENDING before SPI_ACTIVE, otherwise
    # we could correctly read 0 from SPI_ACTIVE, and then read 0
    # from SPI_PENDING the next cycle!
    while (yield from bus.read(SPI_PENDING)) | \
          (yield from bus.read(SPI_ACTIVE)):
        pass
    return (yield from _read_data(bus))


def _test_active(bus):
    while (yield from bus.read(SPI_ACTIVE)):
        pass
    return (yield from _read_data(bus))


def _test_pending(bus):
    while (yield from bus.read(SPI_PENDING)):
        pass
    return (yield from _read_data(bus))


def _test_gen(bus):
    yield from bus.write(SPI_OFFLINE, 0)
    yield from bus.write(SPI_CS_POLARITY, 0)
    yield from bus.write(SPI_CLK_POLARITY, 0)
    yield from bus.write(SPI_CLK_PHASE, 1)
    yield from bus.write(SPI_LSB_FIRST, 0)
    yield from bus.write(SPI_HALF_DUPLEX, 1)
    yield from bus.write(SPI_CLK_DIV_READ, 5)
    yield from bus.write(SPI_CLK_DIV_WRITE, 3)
    yield from _test_xfer(bus, 0b01, 4, 0, 0x90000000)
    print(hex((yield from _test_read(bus))))
    yield from _test_xfer(bus, 0b10, 0, 4, 0x90000000)
    print(hex((yield from _test_read(bus))))
    yield from _test_xfer(bus, 0b11, 4, 4, 0x81000000)
    print(hex((yield from _test_read(bus))))
    yield from _test_xfer(bus, 0b01, 8, 32, 0x87654321)
    yield from _test_xfer(bus, 0b01, 0, 32, 0x12345678)
    print(hex((yield from _test_pending(bus))))
    print(hex((yield from _test_active(bus))))
    return

    yield from bus.write(SPI_HALF_DUPLEX, 0)
    for cpol, cpha, lsb, clk in product(
            (0, 1), (0, 1), (0, 1), (0, 1)):
        yield from bus.write(SPI_CLK_POLARITY, cpol)
        yield from bus.write(SPI_CLK_PHASE, cpha)
        yield from bus.write(SPI_LSB_FIRST, lsb)
        yield from bus.write(SPI_CLK_DIV_READ, clk)
        yield from bus.write(SPI_CLK_DIV_WRITE, clk)
        for wlen, rlen, wdata in product((0, 8, 32), (0, 8, 32),
                                         (0, 0xffffffff, 0xdeadbeef,
                                          0x5555aaaa)):
            xfer_len = wlen + rlen
            yield from _test_xfer(bus, 0b1, wlen, rlen, wdata)
            if cpha == 1 and xfer_len == 0:
                expected_rdata = rdata  # Write will not register.
                # Use prev rdata.
            else:
                expected_rdata = _simulate_shifts(wdata, xfer_len, lsb, 32)
            rdata = (yield from _test_read(bus))
            if expected_rdata != rdata:
                print("ERROR", end=" ")
            print(cpol, cpha, lsb, clk, wlen, rlen,
                  hex(wdata), hex(rdata), hex(expected_rdata))


# The same shift register is used to output and capture data. Tests loop back
# MOSI to MISO. Core samples the input data and then shifts. Data is valid
# after sampling phase. Three consequences of this is:
# 1. It takes n - 1 shifts for n bits of data to be valid (the last shift is
# never performed).
# 2. If MSB != LSB, the LSB or MSB (depending on shift direction) will be
# overwritten during the next sample.
# 3. The contents of the shift register are periodic every width - 1 shifts.
# Shifts begin at n = 2, so n = 1 and n = 32 and n = 63 will be equivalent, as
# will n = 2 and n = 33 etc, where n = wlen + rlen.
# When a shift occurs, the value that was previously in the LSB (or MSB) of
# the shift register is preserved.
def _simulate_shifts(write_val, num_samples, lsb=0, width=32):
    curr_val = write_val
    # n samples require n - 1 shifts
    if lsb:
        for i in range(num_samples - 1):
            curr_val = _ror(_sampr(curr_val, width), width)
        return _sampr(curr_val, width)
    else:
        for i in range(num_samples - 1):
            curr_val = _rol(_sampl(curr_val, width), width)
        return _sampl(curr_val, width)


def _sampl(val, width):
    if ((val >> (width - 1)) ^ (val & 0x01)):
        return val ^ 1
    else:
        return val


def _sampr(val, width):
    if ((val >> (width - 1)) ^ (val & 0x01)):
        return val ^ (1 << width - 1)
    else:
        return val


def _rol(val, width):
    mask = (1 << width) - 1
    msbs = (val << 1) & mask
    lsbs = (val & mask) >> (width - 1)
    return msbs | lsbs


def _ror(val, width):
    mask = (1 << width) - 1
    lsbs = (val & mask) >> 1
    msbs = (val << (width - 1)) & mask
    return msbs | lsbs


class _TestPads:
    def __init__(self):
        self.cs_n = Signal(2)
        self.clk = Signal()
        self.mosi = Signal()
        self.miso = Signal()


class _TestTristate(Module):
    def __init__(self, t):
        oe = Signal()
        self.comb += [
            t.target.eq(t.o),
            oe.eq(t.oe),
            t.i.eq(t.o),
        ]

if __name__ == "__main__":
    from migen.fhdl.specials import Tristate

    pads = _TestPads()
    dut = SPIMaster(pads)
    dut.comb += pads.miso.eq(pads.mosi)
    dut.submodules.bus = bus = CSRBank(dut.get_csrs())
    # from migen.fhdl.verilog import convert
    # print(convert(dut))

    Tristate.lower = _TestTristate
    run_simulation(dut, _test_gen(bus.bus), vcd_name="spi_master.vcd")
