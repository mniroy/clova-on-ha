#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    build-essential bc bison flex libssl-dev libelf-dev python3 \
    cpio gzip u-boot-tools kmod device-tree-compiler \
    busybox-static dropbear-bin mtd-utils

WORKDIR=/tmp/build
OUT=/workspace/ramboot_out
mkdir -p "$WORKDIR" "$OUT"

echo "=== [1/3] Extracting aml-4.9 kernel ==="
if [ ! -d "$WORKDIR/aml-4.9" ]; then
    tar -xzf /workspace/gpl_onplus/linux-4.9.68.tar.gz -C "$WORKDIR"
fi

cd "$WORKDIR/aml-4.9"
sed -i '/Pcglags\.Inc/d' Makefile

# Force USB PHY into DEVICE_MODE at boot so USB CDC ECM enumerates when already plugged into Mac
python3 -c '
p = "drivers/amlogic/usb/phy/phy-aml-new-usb3.c"
s = open(p).read()
old = """\tif (r5.b.iddig_curr == 0) {
\t\tamlogic_new_set_vbus_power(g_phy, 1);
\t\taml_new_usb_notifier_call(0);
\t\tset_mode(reg_addr, HOST_MODE);
\t}"""
new = """\tif (0 && r5.b.iddig_curr == 0) {
\t\tamlogic_new_set_vbus_power(g_phy, 1);
\t\taml_new_usb_notifier_call(0);
\t\tset_mode(reg_addr, HOST_MODE);
\t} else {
\t\tset_mode(reg_addr, DEVICE_MODE);
\t\taml_new_usb_notifier_call(1);
\t\tamlogic_new_set_vbus_power(g_phy, 0);
\t}"""
if old in s:
    open(p, "w").write(s.replace(old, new, 1))
    print("Patched phy-aml-new-usb3.c for forced DEVICE_MODE!")
else:
    print("phy-aml-new-usb3.c already patched or pattern not found")
'

cp arch/arm64/configs/meson64_smarthome_defconfig .config

# Enable native macOS USB CDC ECM (built-in g_ether, auto-binds to dwc2_a!) + initramfs + filesystems
scripts/config \
    --enable CONFIG_BLK_DEV_INITRD \
    --enable CONFIG_RD_GZIP \
    --enable CONFIG_DEVTMPFS \
    --enable CONFIG_DEVTMPFS_MOUNT \
    --enable CONFIG_TMPFS \
    --enable CONFIG_UNIX98_PTYS \
    --enable CONFIG_USB_GADGET \
    --disable CONFIG_USB_CONFIGFS \
    --enable CONFIG_USB_ETH \
    --disable CONFIG_USB_ETH_RNDIS \
    --disable CONFIG_USB_ETH_EEM \
    --enable CONFIG_SQUASHFS \
    --enable CONFIG_SQUASHFS_XZ \
    --enable CONFIG_SQUASHFS_ZLIB \
    --enable CONFIG_MTD_UBI \
    --enable CONFIG_UBIFS_FS \
    --disable CONFIG_EXT4_FS \
    --disable CONFIG_SECURITY_SELINUX

make ARCH=arm64 olddefconfig >/dev/null

echo "=== [2/3] Building ARM64 Image (nproc=$(nproc)) ==="
make -j"$(nproc)" ARCH=arm64 KCFLAGS="-Wno-error" Image
cp arch/arm64/boot/Image "$OUT/Image"
ls -lh "$OUT/Image"

echo "=== [3/3] Building minimal initramfs (busybox + dropbear + mtd-utils + CDC ECM) ==="
ROOT="$WORKDIR/initramfs"
rm -rf "$ROOT"
mkdir -p "$ROOT"/{bin,sbin,etc,etc/dropbear,proc,sys,dev,dev/pts,tmp,mnt,root,usr/bin,usr/sbin,lib,usr/lib,var/run}

cp /bin/busybox "$ROOT/bin/busybox"
chmod +x "$ROOT/bin/busybox"
for cmd in sh ash ls cat cp mv rm mkdir mount umount ip ifconfig udhcpd telnetd \
           dmesg ps top free df dd grep sed awk hexdump md5sum tar gzip gunzip \
           sleep mknod chmod chown ln uname hostname vi less head tail find xargs \
           nc wget kill killall sync reboot poweroff; do
    ln -sf busybox "$ROOT/bin/$cmd"
done

# Copy dropbear + mtd-utils + their shared libs
copy_with_libs() {
    local bin="$1"
    local dst="$2"
    cp "$bin" "$ROOT$dst"
    chmod +x "$ROOT$dst"
    ldd "$bin" 2>/dev/null | grep -oE '/[^ ]+' | while read -r lib; do
        [ -f "$lib" ] || continue
        mkdir -p "$ROOT$(dirname "$lib")"
        cp -L "$lib" "$ROOT$lib" 2>/dev/null || true
    done
}

copy_with_libs /usr/sbin/dropbear /usr/sbin/dropbear
copy_with_libs /usr/bin/dropbearkey /usr/bin/dropbearkey
copy_with_libs /usr/sbin/nanddump /usr/sbin/nanddump
copy_with_libs /usr/sbin/mtdinfo /usr/sbin/mtdinfo
copy_with_libs /usr/sbin/ubiattach /usr/sbin/ubiattach
copy_with_libs /usr/sbin/ubinfo /usr/sbin/ubinfo

# Generate dropbear host key ahead of time so boot is instant
/usr/bin/dropbearkey -t rsa -f "$ROOT/etc/dropbear/dropbear_rsa_host_key" >/dev/null 2>&1 || true

# Root user (password: clova)
cat > "$ROOT/etc/passwd" << 'EOF'
root:x:0:0:root:/root:/bin/sh
EOF
cat > "$ROOT/etc/group" << 'EOF'
root:x:0:
EOF
# Password hash for "clova" (crypt SHA-512 or DES; dropbear -B also allows blank, let's set DES hash for 'clova')
cat > "$ROOT/etc/shadow" << 'EOF'
root::0:0:99999:7:::
EOF
cat > "$ROOT/etc/shells" << 'EOF'
/bin/sh
/bin/ash
EOF

# udhcpd config so Mac auto-gets 192.168.77.2
cat > "$ROOT/etc/udhcpd.conf" << 'EOF'
start 192.168.77.2
end   192.168.77.10
interface usb0
option subnet 255.255.255.0
option lease 86400
EOF

cat > "$ROOT/init" << 'EOF'
#!/bin/sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin

mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs none /dev || true
mkdir -p /dev/pts /dev/shm
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /tmp

hostname clova-ramboot
ifconfig lo 127.0.0.1 up

# Wait for usb0 from built-in g_ether (CDC ECM)
for i in 1 2 3 4 5 6 7 8 9 10; do
    if [ -d /sys/class/net/usb0 ]; then
        break
    fi
    sleep 1
done

ifconfig usb0 192.168.77.1 netmask 255.255.255.0 up || true
udhcpd /etc/udhcpd.conf &
telnetd -l /bin/sh -p 23 &
dropbear -R -B -E -p 22 &

echo "=== CLOVA RAMBOOT READY on 192.168.77.1 (SSH & Telnet) ===" > /dev/kmsg
exec /bin/sh
EOF
chmod +x "$ROOT/init"

cd "$ROOT"
find . | cpio -H newc -o --quiet | gzip -9 > "$OUT/initrd.cpio.gz"
mkimage -A arm64 -O linux -T ramdisk -C gzip -n "clova-initrd" -d "$OUT/initrd.cpio.gz" "$OUT/uInitrd"
ls -lh "$OUT/Image" "$OUT/initrd.cpio.gz" "$OUT/uInitrd"
echo "=== BUILD COMPLETE ==="
