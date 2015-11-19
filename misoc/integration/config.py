from migen import *

from misoc.interconnect.csr import AutoCSR, CSRConstant

class Config(AutoCSR):
    def __setitem__(self, key, value):
        setattr(self, key, CSRConstant(value, name=key))

    def __getitem__(self, key):
        return getattr(self, key).value
