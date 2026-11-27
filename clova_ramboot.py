#!/usr/bin/env python3
"""
Fast & verified RAM-boot for Clova ON (Amlogic A113X) via U-Boot USB (1b8e:c003).
Uses exact 4096-byte DWC_BLK_MAX_LEN blocks (matching Amlogic U-Boot usb_pcd.c),
verifies start + middle + end of every uploaded image in RAM, and boots via `booti`.
"""
import os
import sys
import time
import struct
import usb.core
import usb.util
import usb.backend.libusb1

VID = 0x1B8E
PID = 0xC003

REQ_READ_MEM = 0x02
REQ_WR_LARGE_MEM = 0x11
REQ_IDENTIFY_HOST = 0x20
REQ_TPL_CMD = 0x30
REQ_TPL_STAT = 0x31

ADDR_DTB = 0x01000000     # 16 MB (dtb_mem_addr in U-Boot env!)
ADDR_KERNEL = 0x01080000  # 16.5 MB (loadaddr in U-Boot env!)
ADDR_INITRD = 0x03800000  # 56 MB (safe below 0x05000000 secmon!)

LIBUSB_PATHS = [
    "/opt/homebrew/lib/libusb-1.0.dylib",
    "/usr/local/lib/libusb-1.0.dylib",
]

def get_backend():
    for p in LIBUSB_PATHS:
        if os.path.exists(p):
            return usb.backend.libusb1.get_backend(find_library=lambda _, path=p: path)
    return usb.backend.libusb1.get_backend()

def wait_for_device(backend, timeout_s=90):
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is not None:
        try:
            resp = bytes(dev.ctrl_transfer(0xC0, REQ_IDENTIFY_HOST, 0, 0, 8, timeout=1000))
            print(f"[IDENTIFY] Connected! hex={resp.hex()}", flush=True)
            return dev
        except Exception:
            print("Sesi lama masih nyangkut — silakan CABUT kabel USB dulu...", flush=True)
            end = time.time() + timeout_s
            while time.time() < end:
                if usb.core.find(idVendor=VID, idProduct=PID, backend=backend) is None:
                    print("Terdeteksi dicabut! Sekarang COLOK ULANG kabel USB Clova ON...", flush=True)
                    break
                time.sleep(0.05)

    print(f"Menunggu Amlogic U-Boot (1b8e:c003) selama {timeout_s} detik...", flush=True)
    end = time.time() + timeout_s
    while time.time() < end:
        dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        if dev is not None:
            resp = bytes(dev.ctrl_transfer(0xC0, REQ_IDENTIFY_HOST, 0, 0, 8, timeout=2000))
            print(f"[IDENTIFY] hex={resp.hex()}", flush=True)
            return dev
        time.sleep(0.02)
    raise TimeoutError("Device 1b8e:c003 tidak ditemukan.")

def read_mem_small(dev, addr, length=16):
    return bytes(dev.ctrl_transfer(0xC0, REQ_READ_MEM, addr >> 16, addr & 0xFFFF, length, timeout=2000))

def bulkcmd(dev, cmd, ignore_timeout=False, timeout_s=5.0):
    print(f"[CMD] {cmd}", flush=True)
    try:
        dev.ctrl_transfer(0x40, REQ_TPL_CMD, 0, 1, cmd.encode("ascii") + b"\x00", timeout=2000)
        end = time.time() + timeout_s
        while time.time() < end:
            st = bytes(dev.ctrl_transfer(0xC0, REQ_TPL_STAT, 0, 0, 64, timeout=2000))
            msg = st.split(b"\x00", 1)[0].decode("latin1", errors="replace")
            if msg and not msg.startswith("busy"):
                print(f"  -> {msg}", flush=True)
                return msg
            time.sleep(0.05)
    except Exception as e:
        if ignore_timeout:
            print(f"  -> (booting: {e})", flush=True)
            return "booting"
        raise
    return None

def write_mem(dev, addr, data, block_len=4096):
    """
    Matches Amlogic U-Boot usb_pcd.c: DWC_BLK_MAX_LEN = 8 * 512 = 4096.
    Each bulk ep_out.write() sends exactly 4096 bytes.
    """
    rem = len(data) % block_len
    if rem:
        data = data + (b"\x00" * (block_len - rem))

    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
    )

    max_chunk = 512 * 1024  # 512 KB per REQ_WR_LARGE_MEM control request (superbird_device WRITE_CHUNK_SIZE)
    offset = 0
    total = len(data)
    t0 = time.time()
    while offset < total:
        chunk = data[offset:offset + max_chunk]
        nblocks = len(chunk) // block_len
        ctrl = struct.pack("<IIII", addr + offset, len(chunk), 0, 0)
        dev.ctrl_transfer(0x40, REQ_WR_LARGE_MEM, block_len, nblocks, ctrl, timeout=5000)
        pos = 0
        while pos < len(chunk):
            ep_out.write(chunk[pos:pos + block_len], timeout=5000)
            pos += block_len
        offset += len(chunk)
    dt = time.time() - t0
    print(f"  uploaded {total/1024/1024:.2f} MB to 0x{addr:08x} in {dt:.2f}s", flush=True)

def upload_and_verify(dev, path, addr):
    with open(path, "rb") as f:
        data = f.read()
    print(f"[UPLOAD] {path} ({len(data)} bytes) -> 0x{addr:08x}", flush=True)
    write_mem(dev, addr, data, block_len=4096)

    # Verify start, middle, and END of file in RAM!
    n = len(data)
    offsets = sorted(set([0, min(4096, n - 16), min(65536, n - 16), (n // 2) & ~0xF, (n - 16) & ~0xF]))
    for off in offsets:
        if off < 0 or off + 16 > n:
            continue
        got = read_mem_small(dev, addr + off, 16)
        exp = data[off:off + 16]
        if got != exp:
            raise RuntimeError(f"RAM verify FAILED at +0x{off:x}! got={got.hex()} exp={exp.hex()}")
    print(f"  [VERIFY] Start, Middle, and End ({len(offsets)} offsets up to +0x{offsets[-1]:x}) 100% MATCH!", flush=True)

def main():
    backend = get_backend()
    dev = wait_for_device(backend, timeout_s=90)

    upload_and_verify(dev, "stock_clova.dtb", ADDR_DTB)
    upload_and_verify(dev, "ramboot_out/Image", ADDR_KERNEL)

    bulkcmd(dev, f"setenv dtb_mem_addr 0x{ADDR_DTB:x}")
    bulkcmd(dev, "setenv bootargs rdinit=/init init=/init console=ttyS0,115200 no_console_suspend earlycon=aml_uart,0xff803000")
    bulkcmd(dev, "setenv fdt_high 0x05000000")
    print(f"\n>>> Booting via booti 0x{ADDR_KERNEL:08x} - 0x{ADDR_DTB:08x}...", flush=True)
    bulkcmd(dev, f"booti 0x{ADDR_KERNEL:08x} - 0x{ADDR_DTB:08x}", ignore_timeout=True)

if __name__ == "__main__":
    main()
