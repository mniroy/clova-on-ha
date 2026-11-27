#!/usr/bin/env python3
"""
Watch for Amlogic A113X USB Burn / U-Boot mode (1b8e:c003) and immediately
send Identify (0x20) to hold U-Boot on USB.
Also logs any new USB device that appears while watching.
"""
import sys
import time
import usb.core
import usb.backend.libusb1

LIBUSB_PATHS = [
    "/opt/homebrew/lib/libusb-1.0.dylib",
    "/usr/local/lib/libusb-1.0.dylib",
]

def get_backend():
    import os
    for p in LIBUSB_PATHS:
        if os.path.exists(p):
            return usb.backend.libusb1.get_backend(find_library=lambda _, path=p: path)
    return usb.backend.libusb1.get_backend()

def snapshot_devices(backend):
    devs = {}
    for d in usb.core.find(find_all=True, backend=backend):
        key = (d.bus, d.address, d.idVendor, d.idProduct)
        devs[key] = d
    return devs

def send_identify(dev):
    # Amlogic REQ_IDENTIFY_HOST = 0x20, bmRequestType = 0xC0 (IN | VENDOR | DEVICE)
    try:
        resp = dev.ctrl_transfer(0xC0, 0x20, 0, 0, 8, timeout=1000)
        raw = bytes(resp)
        print(f"  [IDENTIFY] hex={raw.hex()} bytes={list(raw)}", flush=True)
        # Byte 3 typically indicates stage (0 = BootROM/BL1, 1 = U-Boot/BL2, etc.)
        if len(raw) >= 8:
            print(f"  [IDENTIFY] stage/flags: b0..b7 = {[hex(b) for b in raw]}", flush=True)
        return raw
    except Exception as e:
        print(f"  [IDENTIFY] error: {e}", flush=True)
        return None

def main():
    timeout_s = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    backend = get_backend()
    if backend is None:
        print("ERROR: libusb backend not found!", flush=True)
        sys.exit(1)

    baseline = set(snapshot_devices(backend).keys())
    print(f"Watching USB for {timeout_s}s... (baseline: {len(baseline)} devices)", flush=True)
    print("Silakan cabut & colok ulang kabel USB board Clova ON sekarang!", flush=True)

    end_time = time.time() + timeout_s
    seen = set(baseline)

    while time.time() < end_time:
        try:
            current = snapshot_devices(backend)
        except Exception:
            time.sleep(0.05)
            continue

        # Check specifically for Amlogic 1b8e:c003 first
        for key, dev in current.items():
            bus, addr, vid, pid = key
            if vid == 0x1B8E:
                print(f"\n>>> AMLOGIC DETECTED! {vid:04x}:{pid:04x} (bus={bus}, addr={addr})", flush=True)
                try:
                    mfg = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
                    prod = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
                    print(f"    Manufacturer='{mfg}' Product='{prod}'", flush=True)
                except Exception as e:
                    print(f"    (string desc error: {e})", flush=True)
                send_identify(dev)
                print(">>> U-Boot/BootROM berhasil ditangkap! Selesai.", flush=True)
                return

            if key not in seen:
                seen.add(key)
                try:
                    mfg = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
                    prod = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
                except Exception:
                    mfg, prod = "", ""
                print(f"[NEW USB] {vid:04x}:{pid:04x} bus={bus} addr={addr} mfg='{mfg}' prod='{prod}'", flush=True)

        time.sleep(0.02)

    print("\nTimeout: belum ada device 1b8e:c003 yang muncul.", flush=True)

if __name__ == "__main__":
    main()
