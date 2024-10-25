from functools import reduce
from operator import or_

from migen import *
from migen.genlib.fsm import FSM, NextState
from migen.genlib.misc import WaitTimer

from misoc.interconnect import dfi as dfibus
from misoc.interconnect import wishbone


class _AddressSlicer:
    def __init__(self, colbits, bankbits, rowbits, address_align):
        self.colbits = colbits
        self.bankbits = bankbits
        self.rowbits = rowbits
        self.address_align = address_align
        self.addressbits = colbits - address_align + bankbits + rowbits

    def row(self, address):
        split = self.bankbits + self.colbits - self.address_align
        if isinstance(address, int):
            return address >> split
        else:
            return address[split:self.addressbits]

    def bank(self, address):
        split = self.colbits - self.address_align
        if isinstance(address, int):
            return (address & (2**(split + self.bankbits) - 1)) >> split
        else:
            return address[split:split+self.bankbits]

    def col(self, address):
        split = self.colbits - self.address_align
        if isinstance(address, int):
            return (address & (2**split - 1)) << self.address_align
        else:
            return Cat(Replicate(0, self.address_align), address[:split])


@ResetInserter()
@CEInserter()
class _Bank(Module):
    def __init__(self, geom_settings):
        self.open = Signal()
        self.row = Signal(geom_settings.rowbits)

        self.idle = Signal(reset=1)
        self.hit = Signal()

        # # #

        row = Signal(geom_settings.rowbits)
        self.sync += \
            If(self.open,
                self.idle.eq(0),
                row.eq(self.row)
            )
        self.comb += self.hit.eq(~self.idle & (self.row == row))


class Minicon(Module):
    def __init__(self, phy_settings, geom_settings, timing_settings, adr_width=30):
        if phy_settings.memtype in ["SDR"]:
            burst_length = phy_settings.nphases*1  # command multiplication*SDR
        elif phy_settings.memtype in ["DDR", "LPDDR", "DDR2", "DDR3"]:
            burst_length = phy_settings.nphases*2  # command multiplication*DDR
        burst_width = phy_settings.dfi_databits*phy_settings.nphases
        address_align = log2_int(burst_length)

        # # #

        self.dfi = dfi = dfibus.Interface(geom_settings.addressbits,
            geom_settings.bankbits,
            phy_settings.dfi_databits,
            phy_settings.nphases)

        self.bus = bus = wishbone.Interface(burst_width, adr_width=adr_width)

        rdphase = phy_settings.rdphase
        wrphase = phy_settings.wrphase

        precharge_all = Signal()
        activate = Signal()
        refresh = Signal()
        write = Signal()
        read = Signal()

        # Compute current column, bank and row from wishbone address
        slicer = _AddressSlicer(geom_settings.colbits,
                                geom_settings.bankbits,
                                geom_settings.rowbits,
                                address_align)

        # Manage banks
        bank_idle = Signal()
        bank_hit = Signal()

        banks = []
        for i in range(2**geom_settings.bankbits):
            bank = _Bank(geom_settings)
            self.comb += [
                bank.open.eq(activate),
                bank.reset.eq(precharge_all),
                bank.row.eq(slicer.row(bus.adr))
            ]
            banks.append(bank)
        self.submodules += banks

        cases = {}
        for i, bank in enumerate(banks):
            cases[i] = [bank.ce.eq(1)]
        self.comb += Case(slicer.bank(bus.adr), cases)

        self.comb += [
            bank_hit.eq(reduce(or_, [bank.hit & bank.ce for bank in banks])),
            bank_idle.eq(reduce(or_, [bank.idle & bank.ce for bank in banks])),
        ]

        # Timings
        write2precharge_timer = WaitTimer(2 + timing_settings.tWR - 1)
        self.submodules +=  write2precharge_timer
        self.comb += write2precharge_timer.wait.eq(~write)

        pending_refresh = Signal()
        refi_cycles = Signal(bits_for(timing_settings.tREFI), reset=timing_settings.tREFI)
        self.sync += [
            If(refresh,
                pending_refresh.eq(0),
            ),
            If(refi_cycles == 0,
                pending_refresh.eq(1),
                refi_cycles.eq(refi_cycles.reset),
            ).Else(
                refi_cycles.eq(refi_cycles - 1)
            ),
        ]

        sdram_col = Signal.like(slicer.col(bus.adr))
        sdram_col_inc_next = Signal.like(slicer.col(bus.adr))
        sdram_swap_bank = Signal()
        sdram_adr_inc = Signal()

        burst = Signal()

        self.comb += \
            Cat(sdram_col_inc_next, sdram_swap_bank).eq(sdram_col + (1 << address_align))

        self.sync += \
            If(~burst,
                sdram_col.eq(slicer.col(bus.adr)),
            ).Else(
                If(sdram_adr_inc,
                    sdram_col.eq(sdram_col_inc_next),
                )
            )

        rdvalid = dfi.phases[rdphase].rddata_valid
        rdvalid_r = Signal.like(rdvalid)
        self.sync += rdvalid_r.eq(rdvalid)

        read_ended = Signal()
        self.comb += read_ended.eq(rdvalid_r & ~rdvalid)

        # Main FSM
        self.submodules.fsm = fsm = FSM()
        fsm.act("IDLE",
            If(pending_refresh,
                NextState("PRECHARGE-ALL")
            ).Elif(bus.stb & bus.cyc,
                If(bank_hit,
                    If(bus.we,
                        If(bus.cti == 0b010,
                            NextState("BURST-WRITE"),
                        ).Else(
                            NextState("WRITE")
                        )
                    ).Else(
                        If(bus.cti == 0b010,
                            NextState("BURST-READ"),
                        ).Else(
                            NextState("READ")
                        )
                    )
                ).Elif(~bank_idle,
                    If(write2precharge_timer.done,
                        NextState("PRECHARGE")
                    )
                ).Else(
                    NextState("ACTIVATE")
                )
            )
        )
        fsm.act("READ",
            read.eq(1),
            dfi.phases[rdphase].ras_n.eq(1),
            dfi.phases[rdphase].cas_n.eq(0),
            dfi.phases[rdphase].we_n.eq(1),
            dfi.phases[rdphase].rddata_en.eq(1),
            NextState("WAIT-READ-DONE"),
        )
        fsm.act("WAIT-READ-DONE",
            If(dfi.phases[rdphase].rddata_valid,
                bus.ack.eq(1),
                NextState("IDLE")
            )
        )
        fsm.act("WAIT-BURST-READ-DONE",
            bus.ack.eq(dfi.phases[rdphase].rddata_valid),
            If(read_ended,
                NextState("IDLE"),
            ).Elif((bus.cti == 0b111) & bus.ack,
                # Pending reads should be invalidated
                NextState("INVALIDATE-READ"),
            ),
        )
        fsm.act("BURST-READ",
            read.eq(1),
            burst.eq(1),
            dfi.phases[rdphase].ras_n.eq(1),
            dfi.phases[rdphase].cas_n.eq(0),
            dfi.phases[rdphase].we_n.eq(1),
            dfi.phases[rdphase].rddata_en.eq(1),
            bus.ack.eq(dfi.phases[rdphase].rddata_valid),
            sdram_adr_inc.eq(1),

            # Stop the burst
            If(bus.cti == 0b111,
                # Wait out the overly anticipated reads
                NextState("INVALIDATE-READ"),
            ).Elif(sdram_swap_bank,
                # Wait for the read to complete
                NextState("WAIT-BURST-READ-DONE"),
            ),
        )
        fsm.act("INVALIDATE-READ",
            # Invalidate responses by deasserting ACK
            # The last legitimate word was sent out by the end of BURST-READ
            If(read_ended,
                NextState("IDLE"),
            ),
        )
        fsm.act("WRITE",
            write.eq(1),
            dfi.phases[wrphase].ras_n.eq(1),
            dfi.phases[wrphase].cas_n.eq(0),
            dfi.phases[wrphase].we_n.eq(0),
            dfi.phases[wrphase].wrdata_en.eq(1),
            NextState("WRITE-LATENCY")
        )
        fsm.act("BURST-WRITE",
            write.eq(1),
            burst.eq(1),
            sdram_adr_inc.eq(1),
            dfi.phases[wrphase].ras_n.eq(1),
            dfi.phases[wrphase].cas_n.eq(0),
            dfi.phases[wrphase].we_n.eq(0),
            dfi.phases[wrphase].wrdata_en.eq(1),
            bus.ack.eq(1),
            If((bus.cti == 0b111) | sdram_swap_bank,
                NextState("BURST-WRITE-LATENCY"),
            ),
        )
        fsm.act("WRITE-ACK",
            bus.ack.eq(1),
            NextState("IDLE")
        )
        fsm.act("PRECHARGE-ALL",
            precharge_all.eq(1),
            dfi.phases[rdphase].ras_n.eq(0),
            dfi.phases[rdphase].cas_n.eq(1),
            dfi.phases[rdphase].we_n.eq(0),
            NextState("PRE-REFRESH")
        )
        fsm.act("PRECHARGE",
            # do no reset bank since we are going to re-open it
            dfi.phases[0].ras_n.eq(0),
            dfi.phases[0].cas_n.eq(1),
            dfi.phases[0].we_n.eq(0),
            NextState("TRP")
        )
        fsm.act("ACTIVATE",
            activate.eq(1),
            dfi.phases[0].ras_n.eq(0),
            dfi.phases[0].cas_n.eq(1),
            dfi.phases[0].we_n.eq(1),
            NextState("TRCD"),
        )
        fsm.act("REFRESH",
            refresh.eq(1),
            dfi.phases[rdphase].ras_n.eq(0),
            dfi.phases[rdphase].cas_n.eq(0),
            dfi.phases[rdphase].we_n.eq(1),
            NextState("POST-REFRESH")
        )
        fsm.delayed_enter("WRITE-LATENCY", "WRITE-ACK", phy_settings.write_latency-1)
        fsm.delayed_enter("BURST-WRITE-LATENCY", "IDLE", phy_settings.write_latency)
        fsm.delayed_enter("TRP", "ACTIVATE", timing_settings.tRP-1)
        fsm.delayed_enter("TRCD", "IDLE", timing_settings.tRCD-1)
        fsm.delayed_enter("PRE-REFRESH", "REFRESH", timing_settings.tRP-1)
        fsm.delayed_enter("POST-REFRESH", "IDLE", timing_settings.tRFC-1)

        # DFI commands
        for phase in dfi.phases:
            if hasattr(phase, "reset_n"):
                self.comb += phase.reset_n.eq(1)
            if hasattr(phase, "odt"):
                self.comb += phase.odt.eq(1)
            self.comb += [
                phase.cke.eq(1),
                phase.cs_n.eq(0),
                phase.bank.eq(slicer.bank(bus.adr)),
                If(precharge_all,
                    phase.address.eq(2**10)
                ).Elif(activate,
                    phase.address.eq(slicer.row(bus.adr))
                ).Elif(write | read,
                    phase.address.eq(sdram_col)
                )
            ]

        # DFI read datapath
        self.comb += bus.dat_r.eq(Cat(phase.rddata for phase in dfi.phases))

        # DFI write datapath
        dfi_dat_w = Cat(phase.wrdata for phase in dfi.phases)
        dfi_sel = Cat(phase.wrdata_mask for phase in dfi.phases)

        for _ in range(phy_settings.write_latency):
            dfi_dat_w_r, dfi_dat_w = dfi_dat_w, Signal.like(dfi_dat_w)
            dfi_sel_r, dfi_sel = dfi_sel, Signal.like(dfi_sel)
            self.sync += [
                dfi_dat_w_r.eq(dfi_dat_w),
                dfi_sel_r.eq(dfi_sel),
            ]

        self.comb += [
            dfi_dat_w.eq(bus.dat_w),
            dfi_sel.eq(~bus.sel)
        ]
