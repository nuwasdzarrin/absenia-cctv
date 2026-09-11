# Absenia — Absensi Karyawan via CCTV (Face Recognition)

Sistem mencatat **clock-in / clock-out** karyawan secara otomatis dari video CCTV
**TP-Link Tapo** (atau webcam saat uji coba), lalu menulis rekap harian ke **Google Sheet**.
Seluruh pengenalan wajah diproses **lokal di PC** — privasi terjaga, yang keluar ke internet
hanya hasil akhir (nama + jam) ke Google Sheet Anda sendiri.

- **Clock-in**: jendela pagi (default **07:00–09:00**) → wajah yang dikenali dianggap "masuk";
  jam masuk = **kemunculan pertama** di dalam jendela.
- **Clock-out**: jendela sore (default **16:00–18:00**) → wajah yang masih terlihat dianggap
  "pulang"; jam pulang = **kemunculan terakhir** di dalam jendela.
- Di luar kedua jendela itu, sistem **tidur** (hemat CPU & listrik, kamera tidak diproses).

> ⚠️ **Wajib dibaca sebelum produksi.** Data wajah adalah **data biometrik sensitif**
> (UU PDP No. 27/2022). Minta **persetujuan tertulis** karyawan, batasi akses ke folder
> `data/`, dan jangan jadikan hasil sistem sebagai satu-satunya dasar keputusan gaji tanpa
> peninjauan HR. Lihat [bagian 12 — Keamanan & Privasi](#12-keamanan--privasi).

---

## Daftar Isi

1. [Cara kerja & logika absensi](#1-cara-kerja--logika-absensi)
2. [Prasyarat](#2-prasyarat)
3. [Instalasi (Windows)](#3-instalasi-windows)
4. [Uji coba pakai webcam dulu](#4-uji-coba-pakai-webcam-dulu)
5. [Menghubungkan CCTV TP-Link Tapo (RTSP)](#5-menghubungkan-cctv-tp-link-tapo-rtsp)
6. [Enrollment — daftarkan wajah karyawan](#6-enrollment--daftarkan-wajah-karyawan)
7. [Hubungkan Google Sheet (Apps Script)](#7-hubungkan-google-sheet-apps-script)
8. [Menjalankan & auto-start](#8-menjalankan--auto-start)
9. [Konfigurasi lengkap (config.yaml)](#9-konfigurasi-lengkap-configyaml)
10. [Struktur proyek](#10-struktur-proyek)
11. [Troubleshooting](#11-troubleshooting)
12. [Keamanan & Privasi](#12-keamanan--privasi)
13. [Roadmap bertahap](#13-roadmap-bertahap)

---

## 1. Cara kerja & logika absensi

```
Sumber video ──▶ ambil 1 frame tiap ~3 dtk (HANYA saat jendela aktif)
 (Tapo RTSP /       └▶ InsightFace: deteksi wajah + hitung "embedding" 512 angka
  webcam)              └▶ cocokkan (cosine similarity) ke galeri wajah karyawan
                          └▶ aturan absensi (butuh ≥ N deteksi) → simpan ke SQLite
                             └▶ akhir jendela → tulis CSV cadangan + kirim ke Google Sheet
```

**Kenapa RTSP, bukan "API"?** Kamera Tapo tidak menyediakan API video. Yang dipakai adalah
**RTSP** — protokol streaming standar CCTV. PC yang menarik stream lalu memprosesnya. Semua
komputasi berat (deteksi & pengenalan wajah) terjadi di PC Anda.

### Aturan jam masuk / jam pulang (penting dipahami)

Sistem hanya menghitung deteksi yang terjadi **di dalam jendela**. Di luar jendela, deteksi
diabaikan total.

| Aturan | Penjelasan |
|---|---|
| **Jam Masuk** | Waktu **paling awal** wajah dikenali **di dalam** jendela pagi. |
| **Jam Pulang** | Waktu **paling akhir** wajah dikenali **di dalam** jendela sore. |
| Keluar-masuk berkali-kali | Tidak masalah — hanya batas paling awal (masuk) & paling akhir (pulang) yang dipakai. |
| Butuh ≥ `min_detections` | Harus terdeteksi beberapa kali (default 3) sebelum sah, untuk mencegah salah-kenal sesaat. Karena frame diambil tiap ~3 detik, ini terkumpul dalam hitungan detik saat orang berada di ruangan. |

**Contoh (jendela masuk 07:00–09:00):** terdeteksi 06:50 (diabaikan, di luar jendela),
lalu 07:05, 07:20, 08:10 → **Jam Masuk = 07:05** (paling awal di dalam jendela).

**Contoh (jendela pulang 16:00–18:00):** terdeteksi 17:00, 17:15, 17:30, 18:00 →
**Jam Pulang = 18:00** (paling akhir di dalam jendela).

---

## 2. Prasyarat

- **Python 3.11+ (64-bit)** — <https://www.python.org/downloads/> (teruji di 3.12).
- **Webcam** untuk uji coba awal (webcam laptop/USB cukup).
- **Kamera TP-Link Tapo** untuk produksi, satu jaringan (LAN) dengan PC. Lihat
  [bagian 5](#5-menghubungkan-cctv-tp-link-tapo-rtsp).
- **Akun Google** + satu Google Sheet (untuk output). Lihat [bagian 7](#7-hubungkan-google-sheet-apps-script).
- **Microsoft C++ Build Tools** (Windows) — diperlukan untuk memasang `insightface`. Lihat
  [bagian 3](#3-instalasi-windows).
- (Opsional) GPU NVIDIA + `onnxruntime-gpu` untuk lebih cepat. Untuk 1–10 orang, **CPU sudah cukup**.

---

## 3. Instalasi (Windows)

### 3.1 Siapkan virtual environment & dependency

```powershell
# dari folder proyek
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

> **Gunakan `python -m pip`, bukan `pip` langsung.** Di Windows dengan Smart App Control,
> `pip.exe` yang baru dibuat sering diblokir ("An Application Control policy has blocked this
> file"). Memanggil lewat `python -m pip` menghindari blokir itu.

Unduhan model InsightFace `buffalo_l` (~300 MB) terjadi **otomatis & sekali** saat pertama
kali `test_webcam.py`/`enroll.py` dijalankan (butuh internet). Model disimpan di
`C:\Users\<user>\.insightface\models\`.

### 3.2 Dua jebakan umum Windows (dan solusinya)

Instalasi `insightface` mengkompilasi kode C++. Bila muncul error, cek dua hal ini:

| Error saat `pip install` | Penyebab | Solusi |
|---|---|---|
| `An Application Control policy has blocked this file` (DLL Cython) | **Smart App Control** memblokir file native tak bertanda tangan | Matikan Smart App Control: **Windows Security → App & browser control → Smart App Control settings → Off** (⚠️ permanen, perlu restart). |
| `Microsoft Visual C++ 14.0 or greater is required` | Belum ada compiler C++ | Install: `winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"` (~2–4 GB, klik "Yes" pada UAC). |
| `[WinError 32] ... used by another process` (mis. `sklearn`) | Antivirus/Defender mengunci file sesaat | **Ulangi** `python -m pip install -r requirements.txt` (paket sudah ter-cache, cepat). |

### 3.3 Siapkan file rahasia `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Isi (lihat [bagian 5](#5-menghubungkan-cctv-tp-link-tapo-rtsp) untuk `TAPO_*` dan
[bagian 7](#7-hubungkan-google-sheet-apps-script) untuk `APPS_SCRIPT_*`):

```ini
# Kamera Tapo (hanya perlu bila camera.source = "rtsp")
TAPO_RTSP_USER=akun_kamera
TAPO_RTSP_PASS=sandi_kamera
TAPO_IP=192.168.1.100

# Google Sheet via Apps Script Web App
APPS_SCRIPT_URL=https://script.google.com/macros/s/XXXX/exec
APPS_SCRIPT_TOKEN=token_rahasia_anda
```

`.env` sudah masuk `.gitignore` — jangan pernah commit file ini.

---

## 4. Uji coba pakai webcam dulu

**Sangat disarankan** menguji seluruh pipeline dengan webcam sebelum menyentuh CCTV.
Pastikan `config.yaml` → `camera.source: "webcam"`.

```powershell
# 1) Lihat deteksi wajah live (buka jendela kamera)
.\.venv\Scripts\python.exe scripts\test_webcam.py
#    q = keluar, s = simpan snapshot ke data/reports/
#    Warna kotak: hijau = dikenali (ada nama) | kuning = belum di-enroll | merah = wajah terlalu kecil

.\.venv\Scripts\python.exe scripts\test_webcam.py --index 1    # bila webcam lebih dari satu
.\.venv\Scripts\python.exe scripts\test_webcam.py --no-show    # tanpa jendela: ambil 1 frame lalu simpan
```

Alur uji yang disarankan: `test_webcam.py` → lihat wajah terdeteksi (kuning) → lakukan
[enrollment](#6-enrollment--daftarkan-wajah-karyawan) → jalankan lagi → wajah Anda jadi
**hijau + nama**.

### 4.1 Cara menjalankan test absen SEKARANG pakai webcam

Pakai **config testing** (`config.testing.yaml`) yang sudah disetel webcam, jendela "selalu
aktif", dan menulis ke tab **Absensi_Test** (tidak mengotori data produksi). Tidak perlu
mengubah `config.yaml`. Syaratnya: wajah Anda sudah di-[enroll](#6-enrollment--daftarkan-wajah-karyawan).

1. (Opsional) lihat kamera dulu — pastikan wajah Anda terkotak **hijau + nama**:
   ```powershell
   .\.venv\Scripts\python.exe scripts\test_webcam.py
   ```
   Tekan **q** untuk keluar.

2. Jalankan absensi 25 detik — **DUDUK MENGHADAP WEBCAM** selama proses berjalan:
   ```powershell
   .\.venv\Scripts\python.exe -m src.main run --config config.testing.yaml --seconds 25
   ```

3. Lihat hasilnya (di terminal & di tab **Absensi_Test** Google Sheet):
   ```powershell
   .\.venv\Scripts\python.exe -m src.main status --config config.testing.yaml
   ```

**Yang diuji tergantung jam saat menjalankan:**
- **Sebelum 12:00** → menguji **clock-in** (jam masuk).
- **Jam 12:00 ke atas** → menguji **clock-out** (jam pulang).

Jadi Anda bisa menguji keduanya tanpa mengedit jam apa pun. Untuk menghentikan lebih awal,
tekan **Ctrl+C**. Ganti `--seconds 25` sesuai kebutuhan (mis. `--seconds 60`).

---

## 5. Menghubungkan CCTV TP-Link Tapo (RTSP)

Bagian ini rinci karena inilah kunci beralih dari webcam ke CCTV sungguhan.

### 5.1 Gambaran

Absenia menarik video Tapo lewat URL RTSP berformat:

```
rtsp://<USER>:<PASS>@<IP_KAMERA>:554/stream1
```

- `<USER>` / `<PASS>` = **Camera Account** (dibuat di app Tapo) — **bukan** akun/email TP-Link
  yang Anda pakai login ke aplikasi.
- `<IP_KAMERA>` = alamat IP kamera di jaringan lokal (mis. `192.168.1.100`).
- `554` = port RTSP standar Tapo.
- `stream1` = video **HD** (disarankan untuk pengenalan wajah). `stream2` = video SD/lebih
  kecil (lebih ringan, tapi wajah jauh jadi lebih sulit dikenali).

Absenia menyusun URL ini otomatis dari `.env` + `config.yaml`. Anda **tidak menulis URL penuh**
di mana pun — cukup isi `TAPO_USER`, `TAPO_PASS`, `TAPO_IP` di `.env`, dan `rtsp_port`/`rtsp_path`
di `config.yaml`.

### 5.2 Langkah 1 — Buat Camera Account di app Tapo

1. Buka aplikasi **Tapo** di HP → pilih kamera Anda.
2. Masuk **Settings (ikon gerigi) → Advanced Settings → Camera Account**.
   (Di sebagian versi: **Device Settings → Advanced Settings → Camera Account**.)
3. Buat **Username** dan **Password**. **Catat keduanya** — ini yang dipakai di `.env`
   (`TAPO_RTSP_USER`, `TAPO_RTSP_PASS`).

> Bila menu Camera Account tidak ada, **update firmware** kamera dulu
> (Settings → Firmware / Device Info).

### 5.3 Langkah 2 — Temukan IP address kamera

Pilih salah satu cara:

- **Via app Tapo (paling mudah):** Settings (gerigi) → **Device Info** → lihat **IP Address**.
- **Via router:** buka halaman admin router (mis. `192.168.1.1`) → daftar **Connected
  Devices / DHCP Clients** → cari perangkat bernama seperti "Tapo_Camera_XXXX".
- **Via PC (scan jaringan):**
  ```powershell
  # tampilkan perangkat yang terdeteksi di LAN (jalankan setelah "ping" broadcast)
  arp -a
  ```

> **Sangat disarankan: kunci IP kamera (DHCP reservation).** Di halaman admin router, ikat
> alamat IP kamera ke MAC address-nya agar **IP tidak berubah** saat router restart. Kalau IP
> berubah, `TAPO_IP` di `.env` jadi salah dan koneksi gagal.

### 5.4 Langkah 3 — Uji URL RTSP secara independen (pakai VLC)

Sebelum menyentuh Absenia, pastikan stream benar dengan **VLC Media Player**:

1. VLC → **Media → Open Network Stream**.
2. Masukkan (ganti sesuai data Anda):
   ```
   rtsp://akun_kamera:sandi_kamera@192.168.1.100:554/stream1
   ```
3. Klik **Play**. Bila video muncul → RTSP & kredensial benar. Bila diminta user/pass atau
   gagal → cek ulang Camera Account, IP, dan bahwa PC + kamera **satu jaringan**.

### 5.5 Langkah 4 — Konfigurasikan Absenia untuk RTSP

1. Di `.env`:
   ```ini
   TAPO_RTSP_USER=akun_kamera
   TAPO_RTSP_PASS=sandi_kamera
   TAPO_IP=192.168.1.100
   ```
2. Di `config.yaml`:
   ```yaml
   camera:
     source: "rtsp"       # ganti dari "webcam" ke "rtsp"
     rtsp_port: 554
     rtsp_path: "stream1" # "stream1" = HD, "stream2" = SD
   ```

### 5.6 Langkah 5 — FASE 0: uji koneksi & kelayakan kamera (WAJIB)

Ini penentu kelayakan seluruh proyek: apakah sudut & resolusi CCTV benar-benar menangkap
wajah yang bisa dikenali.

```powershell
.\.venv\Scripts\python.exe scripts\test_rtsp.py            # ambil 1 frame + deteksi → data/reports/poc_01.jpg
.\.venv\Scripts\python.exe scripts\test_rtsp.py --show     # jendela live (butuh monitor)
.\.venv\Scripts\python.exe scripts\test_rtsp.py --frames 5 # ambil 5 frame berturut
```

Buka `data/reports/poc_01.jpg`:
- Kotak **hijau** = wajah cukup besar (≥ `min_face_width_px`, layak dikenali).
- Kotak **merah** = wajah terlalu kecil.
- Tidak ada kotak / semua merah → **perbaiki dulu** (lihat 5.7) sebelum lanjut.

### 5.7 Posisi & jaringan kamera (agar akurasi tinggi)

- **Tinggi & sudut:** CCTV yang dipasang tinggi menangkap wajah menyudut ke bawah & kecil —
  sulit dikenali. Idealnya arahkan kamera ke **area pintu masuk setinggi wajah**, atau tambah
  satu kamera khusus di titik masuk.
- **Ukuran wajah:** usahakan lebar wajah **≥ 80–100 px** pada frame (indikatornya di Fase 0).
- **Pencahayaan:** hindari backlight kuat (mis. jendela di belakang orang). Enroll dengan foto
  berkondisi mirip ruangan.
- **Jaringan:** kamera & PC harus **satu LAN**. Koneksi **kabel** ke router lebih stabil untuk
  streaming terus-menerus dibanding WiFi. Absenia otomatis **reconnect** bila stream putus.
- **Resolusi:** pakai `stream1` (HD). Turun ke `stream2` hanya bila CPU keberatan dan wajah
  tetap cukup besar.

### 5.8 (Opsional) ONVIF

Tapo juga mendukung ONVIF (biasanya port `2020`), tapi Absenia memakai RTSP yang lebih
sederhana. Anda tidak perlu ONVIF untuk sistem ini.

---

## 6. Enrollment — daftarkan wajah karyawan

Sistem hanya bisa mengenali orang yang sudah "didaftarkan" (embedding wajahnya tersimpan).

### 6.1 Cara A — dari webcam (paling praktis)

Karyawan duduk menghadap webcam, lalu:

```powershell
.\.venv\Scripts\python.exe scripts\capture_face.py --name budi --count 5
```

Skrip otomatis menyimpan foto yang berisi tepat satu wajah cukup besar ke
`data/faces/budi/`. Ulangi untuk tiap orang (ganti `--name`).

### 6.2 Cara B — dari file foto

Siapkan 3–5 foto per orang (variasi sudut/pencahayaan, satu wajah per foto):

```
data/faces/
├─ budi/   1.jpg  2.jpg  3.jpg
└─ siti/   1.jpg  2.jpg
```

### 6.3 Proses enrollment

```powershell
.\.venv\Scripts\python.exe -m src.enroll               # daftarkan semua orang di data/faces/
.\.venv\Scripts\python.exe -m src.enroll --name budi   # daftar ulang satu orang
.\.venv\Scripts\python.exe -m src.enroll --list        # lihat siapa yang terdaftar
```

**Nama subfolder = nama yang muncul di absensi.** Semakin variatif & jelas fotonya, semakin
akurat pengenalannya.

---

## 7. Hubungkan Google Sheet (Apps Script)

Metode ini paling sederhana untuk non-developer: **tanpa** file kredensial JSON / service
account. Cukup satu skrip di dalam Google Sheet, dan PC mengirim data lewat HTTP POST.

Kolom yang ditulis: **Tanggal · Nama · Jam Masuk · Jam Pulang · Status** (header dibuat
otomatis). Data dikirim ulang = **di-update** berdasarkan (Tanggal, Nama), bukan diduplikasi.

1. Buka/buat **Google Sheet** yang mau dipakai.
2. Menu **Extensions → Apps Script**. Hapus isi editor, **tempel seluruh isi**
   [apps_script/Code.gs](apps_script/Code.gs) dari proyek ini.
3. Pada baris `var TOKEN = "...";`, isi **kata sandi rahasia** buatan Anda. **Catat** — harus
   sama dengan `APPS_SCRIPT_TOKEN` di `.env`.
4. **Deploy → New deployment → Web app**:
   - Execute as: **Me**
   - Who has access: **Anyone** (wajib, agar PC bisa POST tanpa login)
   - **Deploy** → **Authorize** → **salin "Web app URL"**.
5. Isi `.env`: `APPS_SCRIPT_URL=<Web app URL>` dan `APPS_SCRIPT_TOKEN=<token yang sama>`.
6. Di `config.yaml`: `sheets.enabled: true`.
7. **Cek:** buka `APPS_SCRIPT_URL` di browser → harus muncul `{"ok":true,...}`.

> **Bila mengubah `Code.gs`, WAJIB deploy ulang** agar versi live ikut berubah:
> **Deploy → Manage deployments → ikon pensil (Edit) → Version: New version → Deploy**.
> URL tetap sama, jadi `.env` tidak perlu diubah.

Skrip sudah tahan terhadap dua hal umum: (a) Google Sheet meng-coerce teks tanggal menjadi
objek Date — dinormalkan agar upsert tetap cocok; (b) baris duplikat lama akan **dibersihkan
sendiri** saat data dikirim berikutnya.

> **CSV cadangan:** rekap selalu ditulis ke `data/reports/absensi_YYYY-MM-DD.csv` sebagai jaring
> pengaman bila internet putus. Google Sheet tetap sumber utama. Set `sheets.enabled: false`
> bila ingin sementara mematikan pengiriman ke Sheet.

---

## 8. Menjalankan & auto-start

```powershell
.\.venv\Scripts\python.exe -m src.main run                 # loop produksi (biarkan berjalan)
.\.venv\Scripts\python.exe -m src.main run --seconds 25    # uji: berhenti setelah 25 detik
.\.venv\Scripts\python.exe -m src.main status              # rekap hari ini di terminal
.\.venv\Scripts\python.exe -m src.main export              # paksa ekspor hari ini ke CSV + Sheet
.\.venv\Scripts\python.exe -m src.main export --date 2026-09-11
```

`run` otomatis aktif hanya di jendela **07:00–09:00** & **16:00–18:00** (sesuai `config.yaml`),
dan mengekspor rekap ke Google Sheet **saat tiap jendela berakhir**.

### Auto-start saat PC menyala (Windows Task Scheduler)

1. Buat `run_absenia.bat` di folder proyek:
   ```bat
   @echo off
   cd /d "%~dp0"
   call .venv\Scripts\activate.bat
   python -m src.main run
   ```
2. **Task Scheduler → Create Task** → tab **Triggers**: **At log on** →
   tab **Actions**: jalankan `run_absenia.bat`.
3. Buka **Power Options**, pastikan PC **tidak sleep** pada jam kerja (07:00–18:00).

---

## 9. Konfigurasi lengkap (`config.yaml`)

Ada **dua file config** agar setelan produksi tidak perlu diubah-ubah:

| File | Untuk | Cara pakai |
|---|---|---|
| `config.yaml` | **Produksi** — CCTV (rtsp), jendela 07:00–09:00 & 16:00–18:00, tab **Absensi** | dipakai otomatis: `python -m src.main run` |
| `config.testing.yaml` | **Uji coba** — webcam, jendela selalu aktif, sampling cepat, tab **Absensi_Test** | tambahkan flag: `... run --config config.testing.yaml` |

Semua perintah `run` / `status` / `export` menerima `--config <file>`. Alternatif: set
environment variable `ABSENIA_CONFIG`. Tanpa keduanya, `config.yaml` (produksi) yang dipakai.

Daftar kunci (berlaku untuk kedua file):

| Kunci | Arti |
|---|---|
| `camera.source` | `"webcam"` (uji coba) atau `"rtsp"` (CCTV Tapo). |
| `camera.webcam_index` | index webcam bila `source: webcam` (biasanya `0`). |
| `camera.rtsp_port` | port RTSP Tapo (default `554`). |
| `camera.rtsp_path` | `"stream1"` (HD) atau `"stream2"` (SD). |
| `camera.sample_interval_sec` | jarak antar-sampling frame saat jendela aktif (default `3`). |
| `camera.reconnect_delay_sec` | jeda sebelum mencoba menyambung ulang stream yang putus. |
| `recognition.match_threshold` | ambang kecocokan wajah (0–1). Naikkan bila banyak salah-kenal; turunkan bila banyak yang tak terkenali. Mulai `0.40`. |
| `recognition.min_face_width_px` | wajah lebih kecil dari ini (piksel) diabaikan. |
| `recognition.det_size` | ukuran input detektor; lebih besar = lebih teliti untuk wajah kecil, lebih lambat. |
| `recognition.use_gpu` | `true` bila memakai `onnxruntime-gpu`. |
| `attendance.min_detections` | jumlah deteksi minimum sebelum dianggap sah (anti false-positive, default `3`). |
| `attendance.clock_in_window` | jam jendela pagi (`start`/`end`, format `"HH:MM"`). |
| `attendance.clock_out_window` | jam jendela sore. |
| `attendance.workdays` | hari kerja (`0`=Senin … `6`=Minggu). Default `[0,1,2,3,4]`. |
| `sheets.enabled` | `true` untuk kirim ke Google Sheet; `false` = CSV saja. |
| `sheets.worksheet_name` | nama tab tujuan di Google Sheet (default `"Absensi"`). |
| `storage.*` | lokasi database, folder foto, folder CSV. |
| `logging.*` | level & file log (`data/absenia.log`). |

---

## 10. Struktur proyek

```
src/
├─ config.py        # muat config.yaml + .env, susun URL RTSP
├─ db.py            # SQLite: employees, embeddings, attendance
├─ camera.py        # sumber frame: webcam / RTSP + reconnect (make_camera)
├─ recognizer.py    # InsightFace: deteksi + embedding + pencocokan
├─ enroll.py        # daftarkan wajah karyawan ke database
├─ attendance.py    # state machine clock-in/out + aturan ≥N deteksi
├─ sheets.py        # tulis CSV + kirim ke Apps Script Web App
├─ scheduler.py     # loop berbasis jendela waktu (bisa dibatasi durasi)
└─ main.py          # entry point: run / status / export
scripts/
├─ test_webcam.py   # uji deteksi & pengenalan via webcam
├─ test_rtsp.py     # FASE 0: uji koneksi CCTV Tapo + kelayakan wajah
└─ capture_face.py  # rekam foto enrollment dari webcam
apps_script/
└─ Code.gs          # dipasang di Google Sheet (Extensions > Apps Script)
config.yaml           # config PRODUKSI (CCTV, jam kerja, tab Absensi)
config.testing.yaml   # config UJI COBA (webcam, jendela selalu aktif, tab Absensi_Test)
.env · requirements.txt
```

---

## 11. Troubleshooting

### Instalasi
| Gejala | Solusi |
|---|---|
| `pip.exe ... Application Control policy has blocked` | Pakai `python -m pip ...` (bukan `pip`). |
| `... blocked this file` saat build (DLL Cython) | Matikan **Smart App Control** (bagian 3.2). |
| `Microsoft Visual C++ 14.0 or greater is required` | Install **C++ Build Tools** (bagian 3.2). |
| `[WinError 32] ... used by another process` | Ulangi `python -m pip install -r requirements.txt`. |
| Model gagal diunduh | Butuh internet saat pertama jalan; cek firewall/proxy. |

### Kamera / RTSP
| Gejala | Solusi |
|---|---|
| `Gagal membuka stream` / `Gagal membuka kamera RTSP` | Cek IP (`ping <IP>`), Camera Account, dan bahwa PC + kamera satu LAN. Uji dulu di **VLC** (bagian 5.4). |
| IP kamera berubah-ubah | Buat **DHCP reservation** di router (bagian 5.3). |
| Stream sering putus | Pakai kabel LAN ke kamera; naikkan `reconnect_delay_sec`. |
| Wajah tak terdeteksi | Terlalu jauh/menyudut/gelap. Ulang **Fase 0**, perbaiki posisi kamera (bagian 5.7). |
| Webcam tak terbuka | Coba `--index 1`, tutup app lain yang memakai webcam, cek izin kamera Windows. |
| Snapshot webcam blank/putih | Frame awal webcam belum "pemanasan" — skrip sudah menangani dengan warm-up; ulangi bila perlu. |

### Pengenalan / absensi
| Gejala | Solusi |
|---|---|
| Salah kenal (orang A → B) | Naikkan `match_threshold`, tambah foto enrollment variatif, naikkan `min_detections`. |
| Nama tak pernah tercatat | Galeri kosong (`enroll` dulu), atau tidak cukup deteksi dalam jendela. |
| Jam masuk/pulang meleset | Cek jendela di `config.yaml` & jam PC. Ingat: masuk = paling awal, pulang = paling akhir **di dalam** jendela. |

### Google Sheet
| Gejala | Solusi |
|---|---|
| Data tak masuk Sheet | `APPS_SCRIPT_URL`/`TOKEN` salah, Web App belum "Anyone", atau token beda dengan `Code.gs`. Buka URL di browser harus `{"ok":true}`. Data tetap aman di CSV. |
| Baris terduplikasi | Pastikan `Code.gs` versi terbaru sudah **di-deploy ulang** (Manage deployments → New version). Skrip terbaru membersihkan duplikat otomatis. |
| Perubahan `Code.gs` tak berefek | Belum deploy versi baru — lihat catatan di [bagian 7](#7-hubungkan-google-sheet-apps-script). |

---

## 12. Keamanan & Privasi

- **Persetujuan:** data wajah = biometrik sensitif (UU PDP No. 27/2022). Minta persetujuan
  tertulis karyawan sebelum enroll.
- **Data lokal:** foto (`data/faces/`), embedding & log absensi (`data/absenia.db`) berada di
  PC Anda. Batasi akses fisik & folder. Yang keluar ke internet hanya nama + jam ke Google
  Sheet Anda.
- **Rahasia:** `.env` (sandi RTSP, token Sheet) tidak boleh disebar/di-commit. Token Apps
  Script berfungsi sebagai kata sandi karena Web App diakses "Anyone".
- **Bukan bukti tunggal:** hasil face recognition bisa keliru (kembar, masker, cahaya).
  Jadikan alat bantu; sediakan cara HR mengoreksi manual di Sheet.

---

## 13. Roadmap bertahap

**Fase 0** (uji koneksi & kelayakan kamera — WAJIB) → **Fase 1** (enrollment) →
**Fase 2** (uji pengenalan via webcam) → **Fase 3** (hubungkan Google Sheet) →
**Fase 4** (jadwal + auto-start) → **Fase 5: pilot 1 minggu** paralel dengan absensi lama,
sambil menyetel `match_threshold` & posisi kamera sampai akurasi diterima HR.
```
