# Tutorial: Naver Clova ON+ (`NL-S300KRL`) → Linux di RAM + SSH via USB

Target: menjadikan speaker Naver Clova ON+ (board `Linkplay DONUT_MAIN_V05`,
SoC Amlogic A113X) sebagai Linux sementara di RAM, lalu SSH root lewat
jaringan USB (`192.168.77.1`), tanpa mengubah apa pun yang permanen.

> Status dokumen ini: langkah-langkahnya disusun dari repo ini
> (`PROGRESS.md`, `clova_uboot.py`, `clova_ramboot.py`, `usb_watch.py`,
> `build_ramboot/build.sh`, `build_ramboot/fast_rebuild.sh`,
> `stock_clova.dts`, `uboot_env.txt`) dan sudah diaudit terhadap file-file
> itu. Bagian yang **belum terverifikasi di board ini** ditandai begitu —
> menulis tutorial itu gampang, yang sulit adalah membuktikan tiap langkah
> jalan di hardware. Sampai ada log UART0, §7 adalah diagnosis, bukan janji.

---

## 0. Apa yang didapat, dan apa yang tidak

| Dapat | Tidak dapat |
| --- | --- |
| Pegang U-Boot board lewat USB (Identify) | Shell Linux dari firmware pabrik secara permanen |
| Boot Linux sendiri di RAM (kernel + initrd + DTB) | Mengubah bootloader, kernel NAND, TPL, OTP |
| SSH root lewat jaringan USB (`192.168.77.1`) | Akses jaringan Wi-Fi/router dari jalur ini |

Jalur ini **tidak menulis NAND**. Kalau board dicabut, semuanya hilang dan
board kembali seperti semula.

Hardware yang sudah teridentifikasi (`PROGRESS.md` §1, `stock_clova.dts`):

| Komponen | Detail |
| --- | --- |
| Board / Model | `Linkplay DONUT_MAIN_V05` / Clova ON+ (`NL-S300KRL`) |
| SoC | Amlogic A113X, quad Cortex-A53 64-bit (`axg_s420_v03`) |
| RAM | 128 MB DDR3 (`0x8000000`) |
| Storage | 256 MB Parallel SLC NAND, partisi `tpl`, `boot` (10 MB), `system` (112 MB), `nv` (1 MB), `bkupgrade` (~130 MB) |
| Audio | TI `TLV320ADC3101` (mic, I2C) + `TAS5707` (amp, I2C `0x36`/`0x3a`) |
| Wi-Fi / BT | SDIO Wi-Fi + Bluetooth |
| UART0 | 3 pad emas di atas chip A113X: `RXD`, `GND`, `TXD` — 3.3V TTL, `115200 8N1` |
| USB device | U-Boot USB `1b8e:c003` (Amlogic) |

---

## 1. Prasyarat

### 1a. Di Mac (jalur yang dipakai repo ini)

- macOS + kabel **USB-A → USB-C data** (kabel C-to-C Mac tidak memicu 5V,
  dan kabel charge-only tidak bisa data).
- Python 3 + `pyusb` + `libusb` (Homebrew: `/opt/homebrew/lib/libusb-1.0.dylib`).
  Script di repo sudah mencari libusb di situ.
- Docker (untuk build kernel, `arm64 ubuntu:20.04`).
- Board CLOVA dalam keadaan menyala / akan dinyalakan.

```bash
python3 -m venv .venv
.venv/bin/pip install pyusb
```

Tidak ada `udev` di Mac — langkah udev di bawah hanya untuk Linux.

### 1b. Di PC Linux (Fedora/Ubuntu) — varian tutorial aslinya

- User masuk grup `dialout`.
- Python 3 + `pyusb` (diuji: PyUSB **1.3.1**).
- Kabel USB **data** (bukan charge-only).

```bash
python3 -m venv ~/clova-usb-venv
~/clova-usb-venv/bin/pip install pyusb
```

Aturan udev (supaya tidak perlu root), `/etc/udev/rules.d/99-clova-usb.rules`:

```
# CLOVA: akses USB mentah untuk anggota grup dialout, hanya Amlogic 1b8e:c003
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="1b8e", ATTR{idProduct}=="c003", GROUP="dialout", MODE="0660"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## 2. Cara kerja: U-Boot lewat USB

Saat boot, U-Boot (`Jun 21 2019-15:31:28`) menjalankan
`try_auto_burn=update 700 1000;` — ia menunggu ~1 detik di USB `1b8e:c003`.
Di jendela itulah host bisa bicara dengan U-Boot lewat control transfer
vendor (bukan lewat serial).

Protokol yang dipakai script di repo ini (`clova_uboot.py`,
`clova_ramboot.py`, `usb_watch.py`):

| Request | Kode | Arah | Fungsi |
| --- | --- | --- | --- |
| `REQ_READ_MEM` | `0x02` | IN | Baca RAM board |
| `REQ_WR_LARGE_MEM` | `0x11` | OUT | Tulis blok besar ke RAM |
| `REQ_IDENTIFY_HOST` | `0x20` | IN | Identify — menahan U-Boot di mode USB |
| `REQ_TPL_CMD` | `0x30` | OUT | Kirim perintah U-Boot (string + NUL) |
| `REQ_TPL_STAT` | `0x31` | IN | Baca hasil perintah (sampai bukan `busy`) |

Aturan tulis yang penting: tiap blok **4096 byte** (`DWC_BLK_MAX_LEN`
di `usb_pcd.c` U-Boot), chunk maksimal 512 KB per `REQ_WR_LARGE_MEM`.
Script memverifikasi isi RAM di awal, tengah, dan akhir tiap file yang
di-upload — kalau ada yang tidak cocok, berhenti sebelum boot.

Cek board ketangkap:

```bash
python3 usb_watch.py 45
# cabut lalu colok ulang USB Clova ON saat diminta
# yang diharapkan: "AMLOGIC DETECTED! 1b8e:c003" + [IDENTIFY] hex=...
```

Di Mac, cek juga `ioreg -p IOUSB` — `1b8e:c003` harus terlihat.

---

## 3. Dump stock dari board (tanpa solder)

Semuanya sudah pernah berhasil di repo ini, tanpa solder:

```bash
python3 clova_uboot.py
```

Hasilnya (sudah ada di repo):

- `uboot_env.txt` (4.168 byte) — diekspor via
  `env export -t 0x01080000`, dibaca dengan `REQ_READ_MEM`.
  Isi penting: `dtb_mem_addr=0x1000000`, `loadaddr=1080000`,
  `fdt_high=0x20000000`, `bootargs=... console=ttyS0,115200 ...
  earlycon=aml_uart,0xff803000`, `try_auto_burn=update 700 1000;`.
- `stock_clova.dtb` (37.914 byte) & `stock_clova.dts` (61.329 byte) —
  diekstrak via `imgread dtb boot 0x01000000`.
- Partisi `boot` terkonfirmasi berisi `ANDROID!` `boot.img`
  (kernel ~5,77 MB, ramdisk ~2,58 MB).

Simpan file-file ini baik-baik: ini cadangan untuk kembali ke stock.

---

## 4. Build kernel + initramfs (RAM-boot)

Sumber: GPL resmi `clovadevice/onplus` (`gpl_onplus/`), kernel
`linux-4.9.68.tar.gz` (`aml-4.9`, `meson64_smarthome_defconfig`).
Build di Docker `arm64 ubuntu:20.04` — lihat `build_ramboot/build.sh`.

Yang diaktifkan di kernel:

- `CONFIG_USB_GADGET=y`, `CONFIG_USB_ETH=y` — gadget Ethernet **CDC ECM**
  saja (tanpa RNDIS/EEM). ECM dipilih karena macOS mengenalinya native;
  RNDIS di Mac bermasalah.
- `CONFIG_BLK_DEV_INITRD`, `CONFIG_RD_GZIP`, `CONFIG_DEVTMPFS`,
  `CONFIG_SQUASHFS`, `CONFIG_MTD_UBI` / `CONFIG_UBIFS_FS`.
- Patch `drivers/amlogic/usb/phy/phy-aml-new-usb3.c`: paksa PHY ke
  `DEVICE_MODE` setelah inisialisasi (kalau tidak, PHY balik ke `HOST_MODE`
  dan gadget tidak pernah enumerate). `fast_rebuild.sh` menambahkan patch
  kedua: menjadwalkan ulang kerja PHY 200 ms setelah `dwc3` me-reset PHY.

Initramfs (`busybox` + `dropbear` + `telnetd` + `udhcpd` + `mtd-utils`):

- `/init` menunggu `usb0` muncul (maks 10 detik), lalu:
  `ifconfig usb0 192.168.77.1 netmask 255.255.255.0 up`,
  `udhcpd` (Mac dapat `192.168.77.2`–`.10`), `telnetd -p 23`,
  `dropbear -R -B -E -p 22`.
- User root **tanpa password** (`/etc/shadow`: `root::...`, dropbear `-B`
  mengizinkan login kosong). Jadi SSH di sini bukan soal key/password —
  kalau SSH gagal, artinya `usb0` / kernelnya belum hidup, bukan auth.
- `build.sh` menghasilkan `ramboot_out/Image`,
  `ramboot_out/initrd.cpio.gz`, dan `ramboot_out/uInitrd`
  (initramfs yang dipaketkan `mkimage -T ramdisk`).

### Perbedaan `build.sh` vs `fast_rebuild.sh` — ini jebakan yang nyata

- `build.sh` **tidak** men-set `CONFIG_INITRAMFS_SOURCE`: `Image`-nya
  **tidak mengandung initramfs**. Initramfs hanya ada sebagai file
  terpisah (`uInitrd`) yang harus di-upload dan diteruskan ke `booti`.
- `fast_rebuild.sh` **baru** men-set
  `CONFIG_INITRAMFS_SOURCE="$ROOT"` (plus UID/GID 0 dan kompresi gzip),
  sehingga initramfs tertanam di dalam `Image`.

Kalau `Image` dari `build.sh` di-boot dengan `booti ... - ...`
(tanpa initrd), kernel tidak punya `/init` dan panic sebelum USB gadget
jalan. Itu penyebab SSH gagal yang paling mungkin sebelum patch
`d1fa123` — lihat §5.

```bash
# di dalam Docker / lingkungan build
bash build_ramboot/build.sh
ls -lh ramboot_out/   # harus ada: Image, initrd.cpio.gz, uInitrd
```

---

## 5. RAM-boot: upload DTB + kernel + initrd, lalu `booti`

Perintahnya (sudah dipatch di `clova_ramboot.py`, commit `d1fa123`):

```bash
python3 clova_ramboot.py
```

Yang dilakukan script, berurutan:

| File | Alamat RAM | Keterangan |
| --- | --- | --- |
| `stock_clova.dtb` | `0x01000000` (16 MB) | `dtb_mem_addr` di env U-Boot |
| `ramboot_out/Image` | `0x01080000` (16,5 MB) | `loadaddr` di env U-Boot |
| `ramboot_out/uInitrd` | `0x03800000` (56 MB) | aman di bawah `0x05000000` (secmon) |

Tiap file diverifikasi awal/tengah/akhir — harus `100% MATCH`.
Lalu:

```
setenv dtb_mem_addr 0x1000000
setenv bootargs rdinit=/init init=/init console=ttyS0,115200 no_console_suspend earlycon=aml_uart,0xff803000
setenv fdt_high 0x05000000
booti 0x01080000 0x03800000 0x01000000
```

Patch `d1fa123` menambahkan:

- Upload `uInitrd` (sebelumnya `ADDR_INITRD` didefinisikan tapi tidak
  pernah dipakai, dan `booti` memakai `-` = tanpa initrd).
- Validasi magic U-Boot legacy image (`27 05 19 56`) pada `uInitrd` —
  kalau yang di-upload ternyata `initrd.cpio.gz` mentah (magic gzip
  `1f 8b`), script gagal dengan pesan jelas, bukan boot ngawur.
- Fallback: kalau `uInitrd` tidak ada, kembali ke `booti ... - ...`
  dengan warning (hanya jalan kalau `Image` dari `fast_rebuild.sh`).
- Guard: kalau `Image` terlalu besar sampai menabrak alamat initrd,
  berhenti sebelum upload.

Output yang diharapkan di akhir: `Booting via booti 0x01080000
0x03800000 0x01000000...`, lalu koneksi U-Boot putus (itu normal —
kernel mengambil alih).

---

## 6. SSH ke board

Setelah `booti`, di host harus muncul interface jaringan USB baru:

```bash
ifconfig          # Mac: cari interface baru (bukan en0/wifi)
ping 192.168.77.1
ssh root@192.168.77.1
# password: kosong, tekan Enter
```

Kalau SSH belum bisa, coba telnet sebagai pembanding (port 23 juga
dinyalakan `/init`):

```bash
telnet 192.168.77.1 23
```

Yang menandakan sukses: `ping` menjawab, `ssh` masuk sebagai root,
`hostname` menjawab `clova-ramboot`.

---

## 7. Troubleshooting — blocker saat ini

Status terakhir di repo (`PROGRESS.md` §3):

- **Sudah jalan:** upload ke RAM & verifikasi 100% cocok; `bootm`/`booti`
  memutus koneksi U-Boot (LED menyala diam).
- **Belum berhasil:** interface USB Ethernet `192.168.77.1` belum muncul
  di macOS, baik setelah `bootm` maupun `booti`. Pada percobaan terakhir,
  `1b8e:c003` masih terdeteksi di `ioreg` namun `TPL_STAT` timeout.

Artinya, sampai titik itu, SSH **belum pernah** mendapat kesempatan gagal
di level auth — jaringannya sendiri belum ada.

| Gejala | Artinya | Langkah |
| --- | --- | --- |
| `uInitrd` tidak di-upload / `booti ... - ...` | Kernel tanpa `/init` → panic dini | Sudah diperbaiki di `d1fa123`; pastikan `ramboot_out/uInitrd` ada dan jalankan script terbaru (`git pull`) |
| Setelah `booti`, `1b8e:c003` masih di `ioreg` | Kernel tidak mengambil alih USB — `booti` tertahan atau panic sebelum init USB gadget | Butuh log UART0 (di bawah) |
| `TPL_STAT` timeout setelah `booti` | Bisa jadi normal (U-Boot sudah pergi) **atau** kernel hang — tidak bisa dibedakan tanpa UART | Butuh log UART0 |
| Interface muncul, `ping` OK, SSH `connection refused` | Kernel + `usb0` hidup, tapi `dropbear` belum jalan | Cek via telnet 23; cek `/init` sudah sampai `dropbear` |
| Interface muncul, `ping` gagal | `usb0` di board belum dapat IP / `udhcpd` belum jalan | Cek `ifconfig` di host dapat `192.168.77.x` atau tidak |

### Audit DTB (hasil pengecekan `stock_clova.dts`)

Dua controller USB ada dan `status = "okay"` di DTB stock:

- `dwc3@ff500000` (`synopsys, dwc3`, USB 3.0 host) — tanpa `dr_mode`.
- `dwc2_a` (`amlogic, dwc2`, `ff400000`, `device_name = "dwc2_a"`,
  `port-type = <0x2>`, `controller-type = <0x3>`) — ini kandidat UDC
  untuk `g_ether`, dan komentar di `build.sh` mengasumsikan `g_ether`
  auto-bind ke `dwc2_a`.

**Belum terverifikasi:** apakah `g_ether` benar-benar bind ke `dwc2_a`
atau malah ke `dwc3`, dan apakah driver UDC-nya (`CONFIG_USB_DWC2` dsb.)
benar-benar `=y` di `.config` hasil build (bukan hanya `CONFIG_USB_ETH`).
Kalau tidak ada UDC yang ter-bind, `usb0` tidak akan pernah ada
seberhasil apa pun upload-nya. Satu-satunya cara memastikan adalah log
boot — lihat di bawah.

### Log UART0 — langkah yang paling menentukan

Sambungkan USB-to-TTL 3.3V ke 3 pad `UART0` (`115200 8N1`), lalu ulangi
`booti`. Yang dicari di log:

1. Apakah kernel mulai (`Starting kernel ...`, `Uncompressing Linux`)?
2. Apakah ada `Kernel panic - not syncing: No working init found`?
   → initrd tidak kebaca / tidak ada `/init`.
3. Apakah ada `dwc2`, `g_ether`, `usb0`, atau `udc` di log?
   → gadget probe gagal atau berhasil.
4. Apakah ada `dwc3` / PHY error?

Tanpa log ini, semua diagnosis di atas hanya dugaan dari gejala luar.

---

## 8. Setelah SSH aktif

Urutan yang direncanakan di `PROGRESS.md` §4:

1. Backup penuh partisi NAND (`boot`, `system`, `nv`) dengan `nanddump`
   — sebelum eksperimen apa pun yang menyentuh NAND.
2. Inspeksi rootfs `system`: konfigurasi ALSA `TLV320ADC3101` +
   `TAS5707`, driver Wi-Fi, tombol, LED.
3. Pasang client Home Assistant Assist / Wyoming yang ringan
   (Go/Rust/C++, mengingat RAM hanya 128 MB) dan konfigurasi agar jalan
   permanen saat boot normal.

---

## Lampiran: peta file repo

| File | Fungsi |
| --- | --- |
| `PROGRESS.md` | Catatan progres & blocker |
| `usb_watch.py` | Tangkap `1b8e:c003` saat colok, kirim Identify |
| `clova_uboot.py` | Dump env U-Boot & DTB via USB |
| `clova_ramboot.py` | Upload DTB + Image + uInitrd, verifikasi, `booti` |
| `build_ramboot/build.sh` | Build kernel + initramfs (Docker arm64) |
| `build_ramboot/fast_rebuild.sh` | Rebuild cepat + initramfs tertanam di Image |
| `stock_clova.dtb` / `.dts` | Device tree stock hasil dump |
| `uboot_env.txt` | Environment U-Boot stock |
| `20261127_222553.jpg` | Foto identifikasi hardware |
