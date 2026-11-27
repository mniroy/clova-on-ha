#!/bin/bash
set -euo pipefail

WORKDIR=/tmp/build
OUT=/workspace/ramboot_out
ROOT="$WORKDIR/initramfs"
cd "$WORKDIR/aml-4.9"

# Patch phy-aml-new-usb3.c:
# 1. In amlogic_gxl_work: always force DEVICE_MODE + aml_new_usb_notifier_call(1)
# 2. In amlogic_new_usb3_init (called by dwc3 AFTER usb2_init resets the PHY!): schedule phy->work at 200ms!
cat > /tmp/patch_phy.pl << 'EOF'
use strict;
use warnings;
local $/;
open(my $fh, '<', 'drivers/amlogic/usb/phy/phy-aml-new-usb3.c') or die $!;
my $s = <$fh>;
close($fh);

# Force DEVICE_MODE in amlogic_gxl_work
$s =~ s/if \(r5\.b\.iddig_curr == 0\) \{\s*amlogic_new_set_vbus_power\(phy, 1\);\s*aml_new_usb_notifier_call\(0\);\s*set_mode\(reg_addr, HOST_MODE\);\s*\} else \{/if (0) {\n\t} else {/s;

# Schedule phy->work at the end of amlogic_new_usb3_init (after dwc3 finishes resetting usb2phy!)
if ($s !~ /schedule_delayed_work\(&phy->work, msecs_to_jiffies\(200\)\)/) {
    $s =~ s/(r5\.b\.iddig_th = 255;\s*writel\(r5\.d32, usb_new_aml_regs\.usb_r\[5\]\);)/$1\n\tschedule_delayed_work(\&phy->work, msecs_to_jiffies(200));/s;
}

open(my $out, '>', 'drivers/amlogic/usb/phy/phy-aml-new-usb3.c') or die $!;
print $out $s;
close($out);
print "Successfully patched amlogic_new_usb3_init & amlogic_gxl_work!\n";
EOF
perl /tmp/patch_phy.pl

# Verify patch lines
grep -n -C 8 "msecs_to_jiffies(200)" drivers/amlogic/usb/phy/phy-aml-new-usb3.c

# Embed initramfs directly into Image so /init ALWAYS runs even without external initrd!
rm -f "$ROOT/dev/console" "$ROOT/dev/null"
scripts/config --set-str CONFIG_INITRAMFS_SOURCE "$ROOT"
scripts/config --set-val CONFIG_INITRAMFS_ROOT_UID 0
scripts/config --set-val CONFIG_INITRAMFS_ROOT_GID 0
scripts/config --enable CONFIG_INITRAMFS_COMPRESSION_GZIP

export DEBIAN_FRONTEND=noninteractive
if ! which mkimage >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq build-essential bc bison flex libssl-dev libelf-dev cpio gzip u-boot-tools kmod
fi

make ARCH=arm64 olddefconfig >/dev/null
make -j"$(nproc)" ARCH=arm64 KCFLAGS="-Wno-error" Image
cp arch/arm64/boot/Image "$OUT/Image"
ls -lh "$OUT/Image"
