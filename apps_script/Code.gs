/**
 * Absenia — Google Apps Script Web App penerima data absensi.
 *
 * Fungsi: menerima HTTP POST dari PC (src/sheets.py), lalu meng-"upsert" baris
 * absensi ke Google Sheet berdasarkan kombinasi (Tanggal, Nama).
 * Satu baris per karyawan per hari — dikirim ulang = di-update, bukan diduplikasi.
 *
 * ====================== CARA PASANG (sekali saja) ======================
 * 1. Buka Google Sheet yang mau dipakai (atau buat baru).
 * 2. Menu  Extensions > Apps Script.
 * 3. Hapus isi editor, tempel SELURUH file ini.
 * 4. Ganti nilai TOKEN di bawah dengan kata sandi rahasia Anda sendiri
 *    (harus SAMA dengan APPS_SCRIPT_TOKEN di file .env pada PC).
 * 5. Klik  Deploy > New deployment > pilih tipe "Web app".
 *      - Description : Absenia
 *      - Execute as  : Me (email Anda)
 *      - Who has access : Anyone   (wajib, agar PC bisa POST tanpa login)
 *    Klik Deploy, izinkan (Authorize), lalu SALIN "Web app URL".
 * 6. Tempel URL itu ke .env sebagai APPS_SCRIPT_URL.
 *
 * Catatan keamanan: "Anyone" berarti siapa pun yang tahu URL bisa POST, karena itu
 * TOKEN wajib dipakai sebagai kata sandi. Jangan sebar URL & token.
 * Bila mengubah kode ini, Deploy ulang: Deploy > Manage deployments > Edit > New version.
 * ======================================================================
 */

// Kata sandi rahasia (harus SAMA dengan APPS_SCRIPT_TOKEN di .env). Jangan disebar.
// GANTI dengan token Anda sendiri saat memasang. Jangan commit token asli ke git.
var TOKEN = "GANTI_DENGAN_TOKEN_RAHASIA";

// Header kolom (urutan harus cocok dengan yang dikirim src/sheets.py)
var HEADER = ["Tanggal", "Nama", "Jam Masuk", "Jam Pulang", "Status"];

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return _json({ ok: false, error: "Body kosong" });
    }
    var data = JSON.parse(e.postData.contents);

    if (String(data.token || "") !== TOKEN) {
      return _json({ ok: false, error: "Token salah" });
    }

    var wsName = data.worksheet || "Absensi";
    var rows = data.rows || [];
    var sheet = _getOrCreateSheet(wsName);
    var index = _buildIndex(sheet); // map "tanggal||nama" -> nomor baris

    var updated = 0, inserted = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var values = [
        r.tanggal || "",
        r.nama || "",
        r.jam_masuk || "",
        r.jam_pulang || "",
        r.status || ""
      ];
      var key = _normDate(r.tanggal) + "||" + String(r.nama || "").trim();
      if (index[key]) {
        sheet.getRange(index[key], 1, 1, HEADER.length).setValues([values]);
        updated++;
      } else {
        sheet.appendRow(values);
        index[key] = sheet.getLastRow();
        inserted++;
      }
    }

    return _json({ ok: true, updated: updated, inserted: inserted });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// GET sederhana untuk cek Web App hidup (buka URL di browser).
function doGet() {
  return _json({ ok: true, service: "Absenia", message: "Web App aktif. Kirim data via POST." });
}

function _getOrCreateSheet(name) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
  }
  // pastikan header di baris 1
  var first = sheet.getRange(1, 1, 1, HEADER.length).getValues()[0];
  var needHeader = false;
  for (var i = 0; i < HEADER.length; i++) {
    if (first[i] !== HEADER[i]) { needHeader = true; break; }
  }
  if (needHeader) {
    sheet.getRange(1, 1, 1, HEADER.length).setValues([HEADER]);
    sheet.setFrozenRows(1);
  }
  // Migrasi: hapus kolom lama "Deteksi Masuk/Pulang" bila masih tersisa (aman & sekali jalan;
  // hanya menghapus kolom yang judulnya persis nama lama, tidak menyentuh kolom lain).
  for (var c = sheet.getLastColumn(); c > HEADER.length; c--) {
    var h = sheet.getRange(1, c).getValue();
    if (h === "Deteksi Masuk" || h === "Deteksi Pulang") {
      sheet.deleteColumn(c);
    }
  }
  return sheet;
}

// Normalkan nilai Tanggal jadi string "yyyy-MM-dd". Google Sheets sering meng-coerce
// teks "2026-09-11" menjadi objek Date; tanpa ini, kunci upsert tak pernah cocok
// sehingga baris terduplikasi (bukan ter-update).
function _normDate(v) {
  if (Object.prototype.toString.call(v) === "[object Date]") {
    return Utilities.formatDate(v, Session.getScriptTimeZone(), "yyyy-MM-dd");
  }
  return String(v).trim();
}

function _buildIndex(sheet) {
  var index = {};
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return index;
  var data = sheet.getRange(2, 1, lastRow - 1, 2).getValues(); // kolom Tanggal & Nama
  var dupRows = [];
  for (var i = 0; i < data.length; i++) {
    var key = _normDate(data[i][0]) + "||" + String(data[i][1]).trim();
    if (index[key]) {
      dupRows.push(index[key]); // baris lama untuk key ini -> hapus, simpan yang terbaru
    }
    index[key] = i + 2; // nomor baris sheet (1-based, +1 header)
  }
  if (dupRows.length > 0) {
    dupRows.sort(function (a, b) { return b - a; }); // hapus dari bawah agar nomor tak bergeser
    for (var j = 0; j < dupRows.length; j++) {
      sheet.deleteRow(dupRows[j]);
    }
    return _buildIndex(sheet); // bangun ulang indeks setelah pembersihan
  }
  return index;
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
