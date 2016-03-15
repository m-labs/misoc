from migen import *
from migen.genlib.record import *
from migen.genlib import fifo


def _make_m2s(layout):
    r = []
    for f in layout:
        if isinstance(f[1], (int, tuple)):
            r.append((f[0], f[1], DIR_M_TO_S))
        else:
            r.append((f[0], _make_m2s(f[1])))
    return r


class EndpointDescription:
    def __init__(self, payload_layout):
        self.payload_layout = payload_layout

    def get_full_layout(self):
        reserved = {"stb", "ack", "payload", "eop", "description"}
        attributed = set()
        for f in self.payload_layout:
            if f[0] in attributed:
                raise ValueError(f[0] + " already attributed in payload layout")
            if f[0] in reserved:
                raise ValueError(f[0] + " cannot be used in endpoint layout")
            attributed.add(f[0])

        full_layout = [
            ("stb", 1, DIR_M_TO_S),
            ("ack", 1, DIR_S_TO_M),
            ("eop", 1, DIR_M_TO_S),
            ("payload", _make_m2s(self.payload_layout))
        ]
        return full_layout


class Endpoint(Record):
    def __init__(self, description_or_layout):
        if isinstance(description_or_layout, EndpointDescription):
            self.description = description_or_layout
        else:
            self.description = EndpointDescription(description_or_layout)
        Record.__init__(self, self.description.get_full_layout())

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "payload"), name)


class _FIFOWrapper(Module):
    def __init__(self, fifo_class, layout, depth):
        self.sink = Endpoint(layout)
        self.source = Endpoint(layout)

        # # #

        description = self.sink.description
        fifo_layout = [("payload", description.payload_layout), ("eop", 1)]

        self.submodules.fifo = fifo_class(layout_len(fifo_layout), depth)
        fifo_in = Record(fifo_layout)
        fifo_out = Record(fifo_layout)
        self.comb += [
            self.fifo.din.eq(fifo_in.raw_bits()),
            fifo_out.raw_bits().eq(self.fifo.dout)
        ]

        self.comb += [
            self.sink.ack.eq(self.fifo.writable),
            self.fifo.we.eq(self.sink.stb),
            fifo_in.eop.eq(self.sink.eop),
            fifo_in.payload.eq(self.sink.payload),

            self.source.stb.eq(self.fifo.readable),
            self.source.eop.eq(fifo_out.eop),
            self.source.payload.eq(fifo_out.payload),
            self.fifo.re.eq(self.source.ack)
        ]


class SyncFIFO(_FIFOWrapper):
    def __init__(self, layout, depth, buffered=False):
        _FIFOWrapper.__init__(
            self,
            fifo.SyncFIFOBuffered if buffered else fifo.SyncFIFO,
            layout, depth)


class AsyncFIFO(_FIFOWrapper):
    def __init__(self, layout, depth):
        _FIFOWrapper.__init__(self, fifo.AsyncFIFO, layout, depth)


class Multiplexer(Module):
    def __init__(self, layout, n):
        self.source = Endpoint(layout)
        sinks = []
        for i in range(n):
            sink = Endpoint(layout)
            setattr(self, "sink"+str(i), sink)
            sinks.append(sink)
        self.sel = Signal(max=n)

        # # #

        cases = {}
        for i, sink in enumerate(sinks):
            cases[i] = sink.connect(self.source)
        self.comb += Case(self.sel, cases)


class Demultiplexer(Module):
    def __init__(self, layout, n):
        self.sink = Endpoint(layout)
        sources = []
        for i in range(n):
            source = Endpoint(layout)
            setattr(self, "source"+str(i), source)
            sources.append(source)
        self.sel = Signal(max=n)

        # # #

        cases = {}
        for i, source in enumerate(sources):
            cases[i] = self.sink.connect(source)
        self.comb += Case(self.sel, cases)


class _UpConverter(Module):
    def __init__(self, nbits_from, nbits_to, ratio, reverse,
                 report_valid_token_count):
        self.sink = sink = Endpoint([("data", nbits_from)])
        source_layout = [("data", nbits_to)]
        if report_valid_token_count:
            source_layout.append(("valid_token_count", bits_for(ratio)))
        self.source = source = Endpoint(source_layout)
        self.ratio = ratio

        # # #

        # control path
        demux = Signal(max=ratio)
        load_part = Signal()
        strobe_all = Signal()
        self.comb += [
            sink.ack.eq(~strobe_all | source.ack),
            source.stb.eq(strobe_all),
            load_part.eq(sink.stb & sink.ack)
        ]

        demux_last = ((demux == (ratio - 1)) | sink.eop)

        self.sync += [
            If(source.ack, strobe_all.eq(0)),
            If(load_part,
                If(demux_last,
                    demux.eq(0),
                    strobe_all.eq(1)
                ).Else(
                    demux.eq(demux + 1)
                )
            ),
            If(source.stb & source.ack,
                source.eop.eq(sink.eop),
            ).Elif(sink.stb & sink.ack,
                source.eop.eq(sink.eop | source.eop)
            )
        ]

        # data path
        cases = {}
        for i in range(ratio):
            n = ratio-i-1 if reverse else i
            cases[i] = source.data[n*nbits_from:(n+1)*nbits_from].eq(sink.data)
        self.sync += If(load_part, Case(demux, cases))

        if report_valid_token_count:
            self.sync += If(load_part, source.valid_token_count.eq(demux + 1))


class _DownConverter(Module):
    def __init__(self, nbits_from, nbits_to, ratio, reverse,
                 report_valid_token_count):
        self.sink = sink = Endpoint([("data", nbits_from)])
        source_layout = [("data", nbits_to)]
        if report_valid_token_count:
            source_layout.append(("valid_token_count", 1))
        self.source = source = Endpoint(source_layout)
        self.ratio = ratio

        # # #

        # control path
        mux = Signal(max=ratio)
        last = Signal()
        self.comb += [
            last.eq(mux == (ratio-1)),
            source.stb.eq(sink.stb),
            source.eop.eq(sink.eop & last),
            sink.ack.eq(last & source.ack)
        ]
        self.sync += \
            If(source.stb & source.ack,
                If(last,
                    mux.eq(0)
                ).Else(
                    mux.eq(mux + 1)
                )
            )

        # data path
        cases = {}
        for i in range(ratio):
            n = ratio-i-1 if reverse else i
            cases[i] = source.data.eq(sink.data[n*nbits_to:(n+1)*nbits_to])
        self.comb += Case(mux, cases).makedefault()

        if report_valid_token_count:
            self.comb += source.valid_token_count.eq(last)


class _IdentityConverter(Module):
    def __init__(self, nbits_from, nbits_to, ratio, reverse,
                 report_valid_token_count):
        self.sink = sink = Endpoint([("data", nbits_from)])
        source_layout = [("data", nbits_to)]
        if report_valid_token_count:
            source_layout.append(("valid_token_count", 1))
        self.source = source = Endpoint(source_layout)
        assert ratio == 1
        self.ratio = ratio

        # # #

        self.comb += sink.connect(source)
        if report_valid_token_count:
            self.comb += source.valid_token_count.eq(1)


def _get_converter_ratio(nbits_from, nbits_to):
    if nbits_from > nbits_to:
        specialized_cls = _DownConverter
        if nbits_from % nbits_to:
            raise ValueError("Ratio must be an int")
        ratio = nbits_from//nbits_to
    elif nbits_from < nbits_to:
        specialized_cls = _UpConverter
        if nbits_to % nbits_from:
            raise ValueError("Ratio must be an int")
        ratio = nbits_to//nbits_from
    else:
        specialized_cls = _IdentityConverter
        ratio = 1

    return specialized_cls, ratio


class Converter(Module):
    def __init__(self, nbits_from, nbits_to, reverse=False,
                 report_valid_token_count=False):
        cls, ratio = _get_converter_ratio(nbits_from, nbits_to)
        self.submodules.specialized = cls(nbits_from, nbits_to, ratio,
                                          reverse, report_valid_token_count)
        self.sink = self.specialized.sink
        self.source = self.specialized.source


class StrideConverter(Module):
    def __init__(self, layout_from, layout_to, *args, **kwargs):
        self.sink = sink = Endpoint(layout_from)
        self.source = source = Endpoint(layout_to)

        # # #

        nbits_from = len(sink.payload.raw_bits())
        nbits_to = len(source.payload.raw_bits())

        converter = Converter(nbits_from, nbits_to, *args, **kwargs)
        self.submodules += converter

        # cast sink to converter.sink (user fields --> raw bits)
        self.comb += [
            converter.sink.stb.eq(sink.stb),
            converter.sink.eop.eq(sink.eop),
            sink.ack.eq(converter.sink.ack)
        ]
        if isinstance(converter.specialized, _DownConverter):
            ratio = converter.specialized.ratio
            for i in range(ratio):
                j = 0
                for name, width in layout_to:
                    src = getattr(sink, name)[i*width:(i+1)*width]
                    dst = converter.sink.data[i*nbits_to+j:i*nbits_to+j+width]
                    self.comb += dst.eq(src)
                    j += width
        else:
            self.comb += converter.sink.data.eq(sink.payload.raw_bits())


        # cast converter.source to source (raw bits --> user fields)
        self.comb += [
            source.stb.eq(converter.source.stb),
            source.eop.eq(converter.source.eop),
            converter.source.ack.eq(source.ack)
        ]
        if isinstance(converter.specialized, _UpConverter):
            ratio = converter.specialized.ratio
            for i in range(ratio):
                j = 0
                for name, width in layout_from:
                    src = converter.source.data[i*nbits_from+j:i*nbits_from+j+width]
                    dst = getattr(source, name)[i*width:(i+1)*width]
                    self.comb += dst.eq(src)
                    j += width
        else:
            self.comb += source.payload.raw_bits().eq(converter.source.data)
