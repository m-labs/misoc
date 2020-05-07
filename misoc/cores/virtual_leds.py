from misoc.interconnect.csr import *


class VirtualLeds(Module, AutoCSR):
    def __init__(self, max_leds=8):
        self.status = CSRStatus(max_leds)

    def get(self, n):
        virtual_led = Signal()
        self.comb += self.status.status[n].eq(virtual_led)
        return virtual_led
