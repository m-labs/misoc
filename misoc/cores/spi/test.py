SPI_DATA_ADDR, SPI_XFER_ADDR, SPI_CONFIG_ADDR = range(3)
(
    SPI_OFFLINE,
    SPI_ACTIVE,
    SPI_PENDING,
    SPI_CS_POLARITY,
    SPI_CLK_POLARITY,
    SPI_CLK_PHASE,
    SPI_LSB_FIRST,
    SPI_HALF_DUPLEX,
) = (1 << i for i in range(8))


def SPI_DIV_WRITE(i):
    return i << 16


def SPI_DIV_READ(i):
    return i << 24


def SPI_CS(i):
    return i << 0


def SPI_WRITE_LENGTH(i):
    return i << 16


def SPI_READ_LENGTH(i):
    return i << 24


def _test_xfer(bus, cs, wlen, rlen, wdata):
    yield from bus.write(SPI_XFER_ADDR, SPI_CS(cs) |
                         SPI_WRITE_LENGTH(wlen) | SPI_READ_LENGTH(rlen))
    yield from bus.write(SPI_DATA_ADDR, wdata)
    yield


def _test_read(bus, sync=SPI_ACTIVE | SPI_PENDING):
    while (yield from bus.read(SPI_CONFIG_ADDR)) & sync:
        pass
    return (yield from bus.read(SPI_DATA_ADDR))


def _test_gen(bus):
    yield from bus.write(SPI_CONFIG_ADDR,
                         0*SPI_CLK_PHASE | 0*SPI_LSB_FIRST |
                         1*SPI_HALF_DUPLEX |
                         SPI_DIV_WRITE(3) | SPI_DIV_READ(5))
    yield from _test_xfer(bus, 0b01, 4, 0, 0x90000000)
    print(hex((yield from _test_read(bus))))
    yield from _test_xfer(bus, 0b10, 0, 4, 0x90000000)
    print(hex((yield from _test_read(bus))))
    yield from _test_xfer(bus, 0b11, 4, 4, 0x81000000)
    print(hex((yield from _test_read(bus))))
    yield from _test_xfer(bus, 0b01, 8, 32, 0x87654321)
    yield from _test_xfer(bus, 0b01, 0, 32, 0x12345678)
    print(hex((yield from _test_read(bus, SPI_PENDING))))
    print(hex((yield from _test_read(bus, SPI_ACTIVE))))
    return
    for cpol, cpha, lsb, clk in product(
            (0, 1), (0, 1), (0, 1), (0, 1)):
        yield from bus.write(SPI_CONFIG_ADDR,
                             cpol*SPI_CLK_POLARITY | cpha*SPI_CLK_PHASE |
                             lsb*SPI_LSB_FIRST | SPI_DIV_WRITE(clk) |
                             SPI_DIV_READ(clk))
        for wlen, rlen, wdata in product((0, 8, 32), (0, 8, 32),
                                         (0, 0xffffffff, 0xdeadbeef)):
            rdata = (yield from _test_xfer(bus, 0b1, wlen, rlen, wdata, True))
            len = (wlen + rlen) % 32
            mask = (1 << len) - 1
            if lsb:
                shift = (wlen + rlen) % 32
            else:
                shift = 0
            a = (wdata >> wshift) & wmask
            b = (rdata >> rshift) & rmask
            if a != b:
                print("ERROR", end=" ")
            print(cpol, cpha, lsb, clk, wlen, rlen,
                  hex(wdata), hex(rdata), hex(a), hex(b))


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
    # from migen.fhdl.verilog import convert
    # print(convert(dut))

    Tristate.lower = _TestTristate
    run_simulation(dut, _test_gen(dut.bus), vcd_name="spi_master.vcd")
