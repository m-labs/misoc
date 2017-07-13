def split(bit, addresses):
    s0 = []
    s1 = []
    mask = 1 << bit
    for address in addresses:
        if address & mask:
            s1.append(address)
        else:
            s0.append(address)
    return s0, s1


# returns a dict of address -> (bits to test for 0, bits to test for 1) 
def make_decoder(word_size, addresses):
    if len(addresses) == 1:
        return {addresses[0]: ([], [])}
    else:
        for i in reversed(range(word_size)):
            s0, s1 = split(i, addresses)
            if s0 and s1:
                break
        assert s0 and s1
        d0 = make_decoder(i, s0)
        d1 = make_decoder(i, s1)
        r = {}
        for address, (bits0, bits1) in d0.items():
            r[address] = (bits0 + [i], bits1)
        for address, (bits0, bits1) in d1.items():
            r[address] = (bits0, bits1 + [i])
        return r


def make_sel_fun(bits):
    bits0, bits1 = bits
    def sel_fun(x):
        r = 1
        for bit0 in bits0:
            r = r & ~x[bit0]
        for bit1 in bits1:
            r = r & x[bit1]
        return r
    return sel_fun


class WishboneSlaveManager:
    def __init__(self, max_address):
        self.max_address = max_address
        self.slaves = []  # list of (origin, length, interface)

    def add(self, origin, length, interface):
        if origin < 0 or length <= 0 or origin + length > self.max_address:
            raise ValueError("Invalid range for origin/length of Wishbone region")
        if origin & 3 or length & 3:
            raise ValueError("Misaligned Wishbone address")
        def in_this_region(addr):
            return addr >= origin and addr < origin + length
        for o, l, _ in self.slaves:
            if in_this_region(o) or in_this_region(o+l-1):
                raise ValueError("Wishbone conflict with region at 0x{:08x} of length 0x{:x}"
                                 .format(o, l))

        self.slaves.append((origin, length, interface))

    def get_interconnect_slaves(self):
        decoder = make_decoder(30, [origin >> 2 for origin, _, _ in self.slaves])
        ic_slaves = []
        for origin, _, interface in self.slaves:
            ic_slaves.append((make_sel_fun(decoder[origin >> 2]), interface))
        return ic_slaves
