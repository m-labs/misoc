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
    def __init__(self, layout_from, layout_to, ratio, reverse):
        self.sink = sink = Endpoint(layout_from)
        self.source = source = Endpoint(layout_to)

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
            cases[i] = []
            for name, width in layout_from:
                src = getattr(self.sink, name)
                dst = getattr(self.source, name)[n*width:(n+1)*width]
                cases[i].append(dst.eq(src))
        self.sync +=  If(load_part, Case(demux, cases))


class _DownConverter(Module):
    def __init__(self, layout_from, layout_to, ratio, reverse):
        self.sink = sink = Endpoint(layout_from)
        self.source = source = Endpoint(layout_to)

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
            cases[i] = []
            for name, width in layout_to:
                src = getattr(self.sink, name)[n*width:(n+1)*width]
                dst = getattr(self.source, name)
                cases[i].append(dst.eq(src))
        self.comb +=  Case(mux, cases).makedefault()


class _IdentityConverter(Module):
    def __init__(self, layout_from, layout_to, ratio, reverse):
        self.sink = Endpoint(layout_from)
        self.source = Endpoint(layout_to)

        # # #

        self.comb += self.sink.connect(self.source)


def _get_converter_ratio(layout_from, layout_to):
    if len(layout_from) != len(layout_to):
        raise ValueError("Incompatible layouts (number of elements)")

    converter = None
    ratio = None
    for f_from, f_to in zip(layout_from, layout_to):
        (name_from, width_from) = f_from
        (name_to, width_to) = f_to

        # check layouts
        if not isinstance(width_to, int) or not isinstance(width_to, int):
            raise ValueError("Sublayouts are not supported")
        if name_from != name_to:
            raise ValueError("Incompatible layouts (field names)")

        # get current converter/ratio
        if width_from > width_to:
            current_converter = _DownConverter
            if width_from % width_to:
                raise ValueError("Ratio must be an int")
            current_ratio = width_from//width_to
        elif width_from < width_to:
            current_converter = _UpConverter
            if width_to % width_from:
                raise ValueError("Ratio must be an int")
            current_ratio = width_to//width_from
        else:
            current_converter = _IdentityConverter
            current_ratio = 1

        # check converter
        if converter is None:
            converter = current_converter
        if current_converter != converter:
            raise ValueError("Incoherent layout's fields (converter type)")

        # check ratio
        if ratio is None:
            ratio = current_ratio
        if current_ratio != ratio:
            raise ValueError("Incoherent layout's fields (ratio)")

    return (converter, ratio)


class Converter(Module):
    def __init__(self, layout_from, layout_to, reverse=False):
        converter, ratio = _get_converter_ratio(layout_from, layout_to)

        # # #

        self.submodules.converter = converter(layout_from, layout_to,
                                              ratio, reverse)
        self.sink, self.source = self.converter.sink, self.converter.source
