#!/usr/bin/env python3
"""
Clean Amlogic U-Boot USB tool (1b8e:c003) for Clova ON (A113X).
Catches U-Boot on boot, sends Identify, exports U-Boot env to RAM, and reads it back safely.
100% READ-ONLY (never writes to NAND).
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

REQ_RD_LARGE_MEM = 0x12
REQ_IDENTIFY_HOST = 0x20
REQ_TPL_CMD = 0x30
REQ_TPL_STAT = 0x31

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
    existing = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if existing is not None:
        print("Device lama masih tercolok — silakan CABUT kabel USB dulu...", flush=True)
        end = time.time() + timeout_s
        while time.time() < end:
            if usb.core.find(idVendor=VID, idProduct=PID, backend=backend) is None:
                print("Terdeteksi dicabut! Sekarang COLOK ULANG kabel USB Clova ON...", flush=True)
                break
            time.sleep(0.05)
    else:
        print(f"Menunggu Amlogic U-Boot (1b8e:c003) selama {timeout_s} detik...", flush=True)
        print("Silakan COLOK kabel USB Clova ON sekarang!", flush=True)

    end = time.time() + timeout_s
    while time.time() < end:
        dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        if dev is not None:
            return dev
        time.sleep(0.02)
    raise TimeoutError("Device 1b8e:c003 tidak muncul dalam batas waktu.")

def identify(dev):
    resp = bytes(dev.ctrl_transfer(0xC0, REQ_IDENTIFY_HOST, 0, 0, 8, timeout=2000))
    print(f"[IDENTIFY] hex={resp.hex()} bytes={list(resp)}", flush=True)
    return resp

def bulkcmd(dev, cmd, timeout_s=5.0):
    raw = cmd.encode("ascii") + b"\x00"
    dev.ctrl_transfer(0x40, REQ_TPL_CMD, 0, 1, raw, timeout=2000)
    end = time.time() + timeout_s
    while time.time() < end:
        st = bytes(dev.ctrl_transfer(0xC0, REQ_TPL_STAT, 0, 0, 64, timeout=2000))
        msg = st.split(b"\x00", 1)[0].decode("latin1", errors="replace")
        if msg and not msg.startswith("busy"):
            print(f"[CMD] '{cmd}' -> '{msg}'", flush=True)
            return msg
        time.sleep(0.05)
    print(f"[CMD] '{cmd}' -> TIMEOUT", flush=True)
    return None

def read_mem(dev, addr, length):
    """Read memory using REQ_READ_MEM (0x02), 64 bytes per control transfer (superbird-tool method)."""
    out = bytearray()
    off = 0
    while off < length:
        n = min(64, length - off)
        a = addr + off
        chunk = bytes(dev.ctrl_transfer(0xC0, 0x02, a >> 16, a & 0xFFFF, n, timeout=2000))
        out.extend(chunk)
        if b"\x00\x00\x00\x00" in chunk and off > 128:
            break
        off += n
    return bytes(out)

def main():
    timeout_s = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    backend = get_backend()
    dev = wait_for_device(backend, timeout_s)
    ident = identify(dev)

    # Export U-Boot environment to safe RAM scratch address
    addr = 0x01080000
    st = bulkcmd(dev, f"env export -t 0x{addr:08x}")
    if st and "success" in st:
        data = read_mem(dev, addr, 16384)
        env_text = data.split(b"\x00", 1)[0].decode("latin1", errors="replace")
        with open("uboot_env.txt", "w", encoding="utf-8", errors="replace") as f:
            f.write(env_text)
        print(f"\n=== U-BOOT ENV ({len(env_text)} bytes, saved to uboot_env.txt) ===", flush=True)
        print(env_text, flush=True)
    else:
        print("env export gagal, skip read_mem.", flush=True)

if __name__ == "__main__":
    main()
