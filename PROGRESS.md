# Progress Hacking Naver Clova ON+ (`Linkplay DONUT_MAIN_V05`) → Home Assistant Assist Speaker

**Target:** Menjadikan speaker pintar **Naver Clova ON+** (`NL-S300KRL`) sebagai **Home Assistant Assist Satellite** lokal.

---

## 1. Identifikasi Hardware (`20261127_222553.jpg` & `stock_clova.dts`)

| Komponen | Detail |
| :--- | :--- |
| **Board / Model** | `Linkplay DONUT_MAIN_V05` / Naver Clova ON+ (`NL-S300KRL`) |
| **SoC** | **Amlogic A113X** (Quad-core ARM Cortex-A53, 64-bit, `axg_s420_v03`) |
| **RAM** | **128 MB** DDR3 (`EtronTech EM6GC16EWKG-10H`, `0x8000000`) |
| **Storage** | **256 MB** Parallel SLC NAND (`ESMT F59L2G81A`, TSOP-48) |
| **Partisi NAND** | `tpl`, `boot` (10 MB), `system` (112 MB), `nv` (1 MB), `bkupgrade` (~130 MB) |
| **Audio Mic** | TI `TLV320ADC3101` (I2C) + PDM Mic Array (`pdm_din0..3`) |
| **Audio Amp** | TI `TAS5707` Class-D Amp (I2C `0x36` & `0x3a`) |
| **LED & Tombol** | `aml_ledring` (I2C) + `adc_keypad` (`play/plus`, `vol-`, `vol+bt`, `vol+`, `mute+bt`, `bt`, `MUTE`) |
| **Wi-Fi / BT** | SDIO Wi-Fi (`aml_wifi`) + Bluetooth (`bt-dev`) |
| **UART0** | 3 pad bulat emas di atas chip A113X (`UART0 RXD`, `GND`, `UART0 TXD` — 3.3V TTL, `115200 8N1`) |

---

## 2. Source Code GPL & Dump Stock dari Board

- **GPL Resmi (`gpl_onplus/`):** Diunduh dari [`clovadevice/onplus`](https://github.com/clovadevice/onplus), berisi kernel resmi **`linux-4.9.68.tar.gz`** (`aml-4.9`, `meson64_smarthome_defconfig`). *(Catatan: `Uboot.tgz` & `kernel_configs.tgz` di repo tersebut untuk modul lama A31 MIPS).*
- **USB U-Boot Access (`1b8e:c003`):**
  - Port USB-C board **butuh kabel USB-A → USB-C** (kabel C-to-C Mac tidak memicu 5V).
  - Saat boot, U-Boot (`Jun 21 2019-15:31:28`) menjalankan `try_auto_burn=update 700 1000;`, sehingga menunggu 1 detik di USB `1b8e:c003`.
- **Berhasil di-dump via USB tanpa solder:**
  - [`uboot_env.txt`](uboot_env.txt) (4.168 bytes) — diekspor via `env export -t 0x01080000` dan dibaca dengan `REQ_READ_MEM` (`0x02`).
  - [`stock_clova.dtb`](stock_clova.dtb) (37.914 bytes) & [`stock_clova.dts`](stock_clova.dts) (61.329 bytes) — diekstrak via `imgread dtb boot 0x01000000`.
  - Terkonfirmasi partisi `boot` berisi `ANDROID!` `boot.img` (kernel ~5.77 MB, ramdisk ~2.58 MB).

---

## 3. Progress RAM-Boot Linux via USB-C

1. **Environment Build (`Docker` arm64 `ubuntu:20.04`):**
   - [`build_ramboot/build.sh`](build_ramboot/build.sh) & [`build_ramboot/fast_rebuild.sh`](build_ramboot/fast_rebuild.sh) mengkompilasi kernel `aml-4.9` (`Image`) dengan:
     - `CONFIG_USB_ETH=y` (CDC ECM untuk macOS, tanpa RNDIS/EEM).
     - Patch pada `drivers/amlogic/usb/phy/phy-aml-new-usb3.c` untuk memaksa `DEVICE_MODE` setelah inisialisasi PHY.
     - Initramfs (`busybox`, `dropbear` SSH, `telnetd`, `udhcpd`, `mtd-utils`) disematkan ke kernel (`CONFIG_INITRAMFS_SOURCE`) maupun dipaketkan ke [`ramboot_out/uInitrd`](ramboot_out/uInitrd) dan [`ramboot_out/ramboot.img`](ramboot_out/ramboot.img).
2. **Script Host macOS (`.venv` dengan `pyusb` + `pyamlboot`):**
   - [`usb_watch.py`](usb_watch.py) — menangkap `1b8e:c003` saat colok.
   - [`clova_uboot.py`](clova_uboot.py) — dump U-Boot env.
   - [`clova_ramboot.py`](clova_ramboot.py) — upload DTB (`0x01000000`) + `Image` (`0x01080000`) dengan blok `4096` byte, verifikasi RAM (awal, tengah, akhir **100% MATCH**), lalu eksekusi `booti`.

### Status & Blocker Saat Ini
- **Sudah jalan:** Upload ke RAM & verifikasi 100% cocok; `bootm` memutus koneksi U-Boot (LED menyala diam).
- **Belum berhasil:**
  - Interface USB Ethernet (`192.168.77.1`) **belum muncul di macOS** (`ioreg -p IOUSB` / `ifconfig`) baik setelah `bootm` maupun `booti`.
  - Pada percobaan terakhir `booti 0x01080000 - 0x01000000`, `1b8e:c003` masih terdeteksi di `ioreg` namun `TPL_STAT` timeout (kemungkinan `booti` tertahan atau kernel panic sebelum menginisialisasi USB gadget).
  - Belum ada log `UART0` untuk melihat output pasti dari U-Boot/kernel saat proses boot.

---

## 4. Langkah Berikutnya

1. **Observasi Boot Log (Sangat Disarankan):** Sambungkan USB-to-TTL 3.3V ke 3 pad `UART0` (`115200 8N1`) untuk melihat di mana `booti` / `bootm` berhenti atau apakah `g_ether`/`dwc2_a` gagal probe.
2. **Alternatif Tanpa UART (via USB):**
   - Uji format kernel / alamat load untuk `booti` vs `bootm` (misal cek apakah `bootm` menolak image unsigned karena `aml_sec_boot_check` atau `booti` butuh `ramdisk` eksplisit alih-alih `-`).
   - Pastikan `dwc2_a` + `g_ether` atau `configfs` (`rndis` / `ecm`) berhasil bind ke `/sys/class/udc`.
3. **Setelah SSH (`192.168.77.1`) Aktif:**
   - Backup penuh partisi NAND (`boot`, `system`, `nv`) menggunakan `nanddump`.
   - Inspeksi rootfs `system` (konfigurasi ALSA `TLV320ADC3101` + `TAS5707`, driver Wi-Fi, tombol, LED).
   - Pasang client **Home Assistant Assist / Wyoming** ringan (Go/Rust/C++, mengingat RAM hanya **128 MB**) dan konfigurasi agar berjalan permanen saat boot normal.
