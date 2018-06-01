#!/usr/bin/env python3.5

import sys
import os
import time
import asyncio
import asyncserial
import serial
import argparse


if sys.platform == "win32":
    import msvcrt
    import threading

    def init_getkey(callback):
        loop = asyncio.get_event_loop()
        def getkey_thread():
            while True:
                c = msvcrt.getch()
                # HACK: This may still attempt to use the loop
                # after it is closed - see comment below.
                loop.call_soon_threadsafe(callback, c)
        threading.Thread(target=getkey_thread, daemon=True).start()

    def deinit_getkey():
        # Python threads suck.
        pass
else:
    import termios

    def init_getkey(callback):
        global old_termios

        fd = sys.stdin.fileno()
        old_termios = termios.tcgetattr(fd)
        new = old_termios.copy()
        new[3] = new[3] & ~termios.ICANON & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, new)

        loop = asyncio.get_event_loop()
        def callback_wrapper():
            callback(os.read(sys.stdin.fileno(), 1))
        loop.add_reader(sys.stdin.fileno(), callback_wrapper)

    def deinit_getkey():
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, old_termios)



sfl_magic_req = b"sL5DdSMmkekro\n"
sfl_magic_ack = b"z6IHG7cYDID6o\n"

# General commands
sfl_cmd_abort = b"\x00"
sfl_cmd_load  = b"\x01"
sfl_cmd_jump  = b"\x02"

# Replies
sfl_ack_success  = b"K"
sfl_ack_crcerror = b"C"
sfl_ack_unknown  = b"U"
sfl_ack_error    = b"E"


crc16_table = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6,
    0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485,
    0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4,
    0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
    0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
    0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12,
    0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
    0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41,
    0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70,
    0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
    0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F,
    0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E,
    0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D,
    0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C,
    0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
    0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A,
    0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9,
    0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
    0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8,
    0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0
]


def crc16(l):
    crc = 0
    for d in l:
        crc = crc16_table[((crc >> 8) ^ d) & 0xff] ^ (crc << 8)
    return crc & 0xffff


class SFLFrame:
    def __init__(self):
        self.cmd = bytes()
        self.payload = bytes()

    def compute_crc(self):
        return crc16(self.cmd + self.payload)

    def encode(self):
        packet = bytes([len(self.payload)])
        packet += self.compute_crc().to_bytes(2, "big")
        packet += self.cmd
        packet += self.payload
        return packet


class Flterm:
    def __init__(self, port, speed, kernel_image, kernel_address,
                 upload_only, output_only):
        self.kernel_image = kernel_image
        self.kernel_address = kernel_address
        self.upload_only = upload_only
        self.output_only = output_only

        self.port = asyncserial.AsyncSerial(port, baudrate=speed)
        if serial.__version__[0] == "2":
            self.port.ser.setRTS(False)
        else:
            self.port.ser.rts = False

    def init(self):
        if not (self.upload_only or self.output_only):
            self.keyqueue = asyncio.Queue(100)
            def getkey_callback(c):
                self.keyqueue.put_nowait(c)
            init_getkey(getkey_callback)

        if self.upload_only:
            self.main_task = asyncio.ensure_future(self.upload_only_coro())
        else:
            self.main_task = asyncio.ensure_future(self.main_coro())

    async def send_frame(self, frame):
        while True:
            await self.port.write_exactly(frame.encode())
            reply = await self.port.read(1)
            if reply == sfl_ack_success:
                return
            elif reply == sfl_ack_crcerror:
                pass  # retry
            else:
                print("[FLTERM] Got unknown reply '{}' from the device, aborting.".format(reply))
                raise ValueError

    async def upload(self, filename, address):
        with open(filename, "rb") as f:
            data = f.read()
        print("[FLTERM] Uploading {} ({} bytes)...".format(filename, len(data)))
        current_address = address
        position = 0
        length = len(data)
        start = time.time()
        while len(data):
            sys.stdout.write("|{}>{}| {}%\r".format('=' * (20*position//length),
                                                    ' ' * (20-20*position//length),
                                                    100*position//length))
            sys.stdout.flush()
            frame = SFLFrame()
            frame_data = data[:251]
            frame.cmd = sfl_cmd_load
            frame.payload = current_address.to_bytes(4, "big")
            frame.payload += frame_data
            try:
                await self.send_frame(frame)
            except ValueError:
                return
            current_address += len(frame_data)
            position += len(frame_data)
            try:
                data = data[251:]
            except:
                data = []
        end = time.time()
        elapsed = end - start
        print("[FLTERM] Upload complete ({0:.1f}KB/s).".format(length/(elapsed*1024)))
        return length

    async def boot(self):
        print("[FLTERM] Booting the device.")
        frame = SFLFrame()
        frame.cmd = sfl_cmd_jump
        frame.payload = self.kernel_address.to_bytes(4, "big")
        await self.send_frame(frame)

    async def answer_magic(self):
        print("[FLTERM] Received firmware download request from the device.")
        await self.port.write_exactly(sfl_magic_ack)
        try:
            await self.upload(self.kernel_image, self.kernel_address)
        except FileNotFoundError:
            print("[FLTERM] File not found")
        else:
            await self.boot()
        print("[FLTERM] Done.");

    async def main_coro(self):
        magic_detect_buffer = b"\x00"*len(sfl_magic_req)
        port_reader = None
        key_getter = None
        while True:
            if port_reader is None:
                port_reader = asyncio.ensure_future(self.port.read(1024))
            fs = [port_reader]
            if not self.output_only:
                if key_getter is None:
                    key_getter = asyncio.ensure_future(self.keyqueue.get())
                fs += [key_getter]
            try:
                done, pending = await asyncio.wait(
                    fs, return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                for f in fs:
                    f.cancel()
                    try:
                        await f
                    except asyncio.CancelledError:
                        pass
                raise
            if port_reader in done:
                data = port_reader.result()
                port_reader = None
                sys.stdout.buffer.write(data)
                sys.stdout.flush()

                if self.kernel_image is not None:
                    for c in data:
                        magic_detect_buffer = magic_detect_buffer[1:] + bytes([c])
                        if magic_detect_buffer == sfl_magic_req:
                            await self.answer_magic()
                            break

            if key_getter in done:
                await self.port.write(key_getter.result())
                key_getter = None

    async def upload_only_coro(self):
        magic_detect_buffer = b"\x00"*len(sfl_magic_req)
        while True:
            data = await self.port.read(1024)
            sys.stdout.buffer.write(data)
            sys.stdout.flush()

            for c in data:
                magic_detect_buffer = magic_detect_buffer[1:] + bytes([c])
                if magic_detect_buffer == sfl_magic_req:
                    await self.answer_magic()
                    return

    async def close(self):
        if not (self.upload_only or self.output_only):
            deinit_getkey()
        self.main_task.cancel()
        try:
            await self.main_task
        except asyncio.CancelledError:
            pass
        finally:
            self.port.close()


def _get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", help="serial port")
    parser.add_argument("--speed", default=115200, help="serial baudrate")
    parser.add_argument("--kernel", default=None, help="kernel image")
    parser.add_argument("--kernel-addr", type=lambda a: int(a, 0),
                        default=0x40000000, help="kernel address")
    parser.add_argument("--upload-only", default=False, action="store_true",
                        help="only upload kernel")
    parser.add_argument("--output-only", default=False, action="store_true",
                        help="do not receive keyboard input or require a pty")
    return parser.parse_args()


def main():
    if os.name == "nt":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    else:
        loop = asyncio.get_event_loop()
    args = _get_args()
    flterm = Flterm(args.port, args.speed, args.kernel, args.kernel_addr,
                    args.upload_only, args.output_only)
    try:
        flterm.init()
        loop.run_until_complete(flterm.main_task)
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(flterm.close())
        loop.close()


if __name__ == "__main__":
    main()
