# Bruno — Frappe REST API Toolkit

Buka folder `bruno/` sebagai collection di Bruno. Collection `.bru` ini berisi
**27 request**, dengan payload siap diedit, dokumentasi pada tab Docs, native saved
response examples, dan pemeriksaan respons untuk flow public/password/JWT/validation.
Contoh tersimpan bersifat **ilustratif dan tersanitasi**, bukan rekaman produksi.

## Inventory dan perubahan

| Folder | Request / API | Status dan sumber |
| --- | --- | --- |
| Public | Ping GET | Public RPC: `api.ping.ping` |
| Public | Calculate GET + POST add/subtract/multiply/divide | Public RPC: `api.calculator.calculate`; DTO + pipes, validation 422 |
| Public | Divide by zero, invalid operation | Contoh negatif endpoint calculator yang sama |
| Login | Login, Complete MFA | Password JWT baru: `api.auth.login`; tanpa API key atau authenticated sid |
| Login | Current User, Refresh, Revoke | Own JWT identity dan lifecycle; tag `password-login`, MFA terpisah dengan tag `mfa` |
| Authentication | Issue, Refresh, Revoke | JWT P1: `api.auth.issue`, `.refresh`, `.revoke` |
| Authentication | Current User | Native `frappe.auth.get_logged_user`, memakai JWT auth hook app; endpoint Frappe tidak diubah |
| Authentication | Revoked Refresh Rejected | Verifikasi negatif bahwa revoke mencegah refresh berikutnya |
| Customer | Create Customer, invalid email | Public RPC: `api.customer.create`; DTO + pipes |
| Administration | Get API Settings, Update JWT Settings | Native REST resource app SingleDoc; schema ditambah tab Authentication dan prioritas field → site_config |
| Administration | List/Get API Log | Native REST resource untuk audit log app |
| Administration | List/Get API Refresh Token | Native REST resource untuk metadata lifecycle baru; bukan refresh credential |
| Administration | Clear Old API Logs | Native document-method route ke controller app `APISettings.clear_logs_now` |

Request dan native examples memakai nama RPC pendek dari
`override_whitelisted_methods` di `api/hooks.py`. Implementasi tetap di
`api/api/`; URL panjang tetap aktif. Reusable auth kini berada di
`api/services/auth/`: `jwt.py`, `password.py`, `refresh_tokens.py`, `settings.py`,
`audit.py`, dan `users.py`. Import Python internal mengikuti lokasi baru;
alias RPC publik `api.auth.login`, `.issue`, `.refresh`, dan `.revoke` tetap sama.
Contoh metadata API Log sengaja tetap memakai nama implementasi panjang, karena
logger dan rate limiter mengikuti fungsi asli. Route resource administrasi dan
`frappe.auth.get_logged_user` tidak diubah.

Collection ini bukan daftar seluruh API Frappe/ERPNext. Helper internal seperti
`get_jwt_settings`, `initialize_jwt_settings`, `rotate`, atau `clear_old_logs`
yang tidak di-whitelist bukan endpoint RPC publik.

Auth hook kini `api.services.auth.jwt.validate`; hook install/migrate memakai
`api.services.auth.settings.initialize_jwt_settings`. Setelah deployment
reorganisasi ini, jalankan `bench --site <site> clear-cache` dan `bench restart`.
DocType tidak berubah: tidak perlu migrasi schema, regenerasi signing key, atau
penghapusan settings, token, maupun audit data.

## Environment dan credential

Environment `Local` berisi `base_url=http://restapi.localhost:8000` tanpa trailing
slash. Ganti URL sesuai runtime Anda. Credential dibaca dari environment process
atau file `bruno/.env` yang di-ignore:

```bash
cd bruno
cp .env.example .env
# Edit .env: FRAPPE_LOGIN_USER dan FRAPPE_LOGIN_PASSWORD untuk password login.
# FRAPPE_LOGIN_OTP opsional untuk langkah MFA; isi hanya kode native saat ini.
# FRAPPE_API_KEY dan FRAPPE_API_SECRET hanya untuk folder Authentication.
```

Jangan commit `.env`, token, cookie, atau private environment. `.env.example`
berisi nama variabel saja. `Local.bru` memetakan process env `FRAPPE_LOGIN_USER`,
`FRAPPE_LOGIN_PASSWORD`, `FRAPPE_LOGIN_OTP` ke `login_user`, `login_password`,
`login_otp`. `client_id=bruno-review` tetap label runtime, bukan credential.
Untuk secret sementara gunakan variable secret Bruno pada environment privat;
jangan menyimpan password/OTP atau `api_key`/`api_secret` ke Local.bru tracked.

Response login/issue/refresh disimpan lewat `bru.setVar` sebagai **runtime variables**:
`access_token` dan `refresh_token`. Password login juga menyimpan own safe profile
di `login_user_profile`, serta `login_tmp_id` privat hanya selama challenge MFA.
Tidak ada script yang mencetak credential/token atau menulisnya ke disk.
Runtime GUI bertahan di collection selama sesi aplikasi; CLI tidak membawa state
ke invocation berikutnya. Login baru membersihkan state login lama sebelum HTTP.
Revoke pada Login membersihkan pair/profile/challenge; Revoke pada Authentication
tetap menyimpan token revoked sementara untuk satu request verifikasi negatif.

## Public smoke — tanpa credential

```bash
cd bruno
bru run Public --env Local --disable-cookies --bail
# Alternatif filtering semua request public:
bru run -r --tags smoke --env Local --disable-cookies --bail
```

Untuk port atau host lain:

```bash
bru run Public --env Local --env-var base_url=http://127.0.0.1:8017 --disable-cookies --bail
```

API Settings harus mengizinkan API dan guest. Calculator tidak membuat data
bisnis, tetapi request dapat menghasilkan API Log. Error 422 pada dua contoh
negatif adalah hasil yang diharapkan dan membuat test lulus.

## Password JWT — tanpa API key/secret

Dengan `FRAPPE_LOGIN_USER` dan `FRAPPE_LOGIN_PASSWORD` terisi privat:

```bash
bru run -r --tags password-login --env Local --disable-cookies --bail
```

Urutan folder Login: **Login → Current User → Refresh → Revoke**. Hanya empat
request ini memiliki tag `password-login`; tidak ada bootstrap API key.
Folder Login terurut sebelum Authentication, tetapi `--tags auth-flow` tetap
hanya menjalankan flow API-key lama. Jangan menjalankan seluruh collection
rekursif tanpa tag; mutasi dan kedua flow auth mempunyai prasyarat berbeda.

Login mengirim `usr`, `pwd`, dan label `client_id` ke
`POST /api/method/api.auth.login` (override ke `api.api.auth.login`).
Credential dibaca dari secret process environment, tanpa normalisasi; script
memakai serialisasi object JSON agar karakter khusus password tetap utuh.
Sukses mengembalikan JWT pair dan `message.user`, **profil milik user yang login**,
bukan full User document. Field yang boleh ada hanya `name`, `email`, `first_name`,
`last_name`, `full_name`, `user_image`, `language`, `time_zone`, `user_type`, `roles`.
Tidak ada password, hash, API key/secret, atau data profil user lain.
Current User membandingkan canonical identity JWT dengan `user.name`, bukan
input `usr` yang mungkin merupakan username.

Backend memakai native LoginManager: disabled password login, failed-login
tracking per user/IP, enabled user, MFA, pembatasan IP/login hours, forced password
reset, dan login hooks tetap berlaku. Password reset wajib menghasilkan native
error, bukan token; selesaikan reset melalui Frappe sebelum mengulang login.
Login **tidak membuat authenticated Frappe `sid`**, dan tidak bergantung pada
session/cookie. Gunakan `--disable-cookies`; JWT adalah credential request berikutnya.

### MFA dua langkah

1. Jalankan **Login**. Jika native MFA dibutuhkan, HTTP 200 berisi
   `message = {mfa_required: true, tmp_id: "...", verification: {...}}`.
   Tidak ada token atau `user`. Script hanya menyimpan `login_tmp_id` privat;
   jangan salin cached password/secret, challenge atau OTP ke file/log.
2. Isi kode native saat ini lewat `FRAPPE_LOGIN_OTP`, atau secret variable
   `login_otp` pada environment GUI privat. Jalankan **Complete MFA** dalam
   runtime yang sama. Request mengirim `otp`, `tmp_id`, `client_id`, **tanpa
   mengirim ulang password**. Sukses menyimpan pair + own profile dan menghapus
   runtime tmp_id. Lanjutkan Current User → Refresh → Revoke secara berurutan.

Complete MFA hanya memiliki tag **`mfa`**, bukan `password-login` atau `auth-flow`.
Jika flow `password-login` mendapat challenge, Current User berhenti sebelum HTTP
dengan instruksi menyelesaikan MFA; jangan menganggap challenge sebagai login sukses.
Untuk email/SMS yang memerlukan interaksi setelah challenge, gunakan GUI dan
jalankan request satu per satu. Mengubah process env pada terminal lain tidak
mengubah environment process Bruno yang sudah berjalan; gunakan secret GUI privat.
Invocation CLI baru `--tags mfa` tidak membawa tmp_id dari invocation sebelumnya.
Untuk kode yang sudah tersedia dan masih valid, semua langkah dapat dijalankan
dalam **satu invocation** dengan request MFA dipilih eksplisit:

```bash
bru run Login/01-Login.bru Login/02-Complete-MFA.bru \
  Login/03-Current-User.bru Login/04-Refresh.bru Login/05-Revoke.bru \
  --env Local --disable-cookies --bail
```

Challenge expired/hilang/replayed ditolak native tanpa token/profile. Mulai
login baru jika challenge expired; challenge sukses dikonsumsi dan tidak boleh
diulang. Format `verification` dan detail native error mengikuti konfigurasi
Frappe; saved response examples hanya ilustrasi tersanitasi, bukan rekaman.

Login memakai arsitektur `@endpoint` yang sama: DTO + pipes, `normalize=false`,
policy `api_enabled`, telemetry `AUTH_METADATA_ONLY`, rate limit **10/IP/menit**.
Login, challenge, continuation, dan kegagalan tetap `Cache-Control: no-store`.
`enable_api=0` memblokir login; kebijakan guest endpoint bisnis bukan syarat login.
Metadata-only tidak menyimpan payload/password/OTP/token/profile di API Log,
termasuk jika masking dimatikan. Jangan aktifkan console logging atau ekspor
header/body report; request/response mengandung credential privat.

## JWT end-to-end — bootstrap API key lama

```bash
bru run Authentication --env Local --disable-cookies --bail
```

Atau pilih flow yang sama dari collection: `bru run -r --tags auth-flow --env Local --disable-cookies --bail`.
File dan tag Authentication tetap tidak berubah; password login tidak diperlukan.

Urutan: **Issue → Current User → Refresh → Revoke → Revoked Refresh Rejected**.
Flow ini membuat dan menyimpan refresh-family nyata lalu merevokenya; record audit
tidak dihapus. Label default `client_id=bruno-review` memudahkan review di Desk.

- Issue memakai native `Authorization: token <api_key>:<api_secret>`.
- Current User memakai JWT bearer terbaru.
- Refresh/revoke sengaja `auth: none`, tanpa header JWT expired.
- Jangan jalankan refresh secara paralel atau retry token lama. Reuse mencabut
  seluruh family; client perlu single-flight refresh.
- Revoke tidak langsung membatalkan access JWT yang sudah terbit; JWT berlaku
  sampai expiry. Client tetap membuang pair setelah logout.
- Secret/issuer/audience berubah: access JWT lama ditolak, refresh valid masih
  dapat menerbitkan pair baru. TTL access berlaku untuk token berikutnya; refresh
  family lama tetap memakai absolute expiry aslinya.

Gunakan `--disable-cookies` agar session/cookie lama tidak memengaruhi hasil auth.
Tidak ada automatic refresh/retry tersembunyi pada collection ini.

Auth memakai decorator `@endpoint` yang sama dengan endpoint bisnis, dengan DTO,
pipes, normalisasi credential dinonaktifkan, dan telemetry metadata-only.
`enable_api=0` memblokir login/issue/refresh/revoke (503). `allow_guest_access=0`
tidak memblokir login atau refresh/logout dengan credential valid. Native error
status tetap dipertahankan; payload dan token tidak dicatat walaupun masking API Log dimatikan.

## Protected reads dan detail

Jalankan login/issue dan request protected dalam **invocation yang sama**, misalnya:

```bash
bru run Authentication/01-Issue.bru "Administration/Get API Settings.bru" \
  "Administration/List API Logs.bru" "Administration/List Refresh Token Metadata.bru" \
  --env Local --disable-cookies --bail
```

Butuh credential **System Manager** untuk administrasi. User integrasi biasa
mendapat 403 pada resource admin. Untuk detail log/session, ambil `name` dari list,
lalu isi `api_log_name` atau `refresh_token_name` pada GUI/runtime atau `--env-var`.

Detail API Refresh Token native menerapkan field-level permissions untuk pengguna
non-Administrator. Administrator melewati filtering tersebut: gunakan request
**List Refresh Token Metadata** dengan proyeksi field aman jika memakai Administrator.
Jangan mengekspor hash maupun payload/header log yang berisi informasi privat.

## Mutasi yang harus diaktifkan secara eksplisit

Default `allow_mutations=false`. Request berikut berhenti sebelum HTTP kecuali
variabel environment tersebut bernilai `true`:

- `Customer/Create customer.bru` — membuat dokumen Customer.
- `Administration/Update JWT Settings.bru` — mengubah konfigurasi authentication.
- `Administration/Clear Old API Logs.bru` — **menghapus log lama permanen**.

Di CLI gunakan `--env-var allow_mutations=true`; pada GUI tambahkan variabel
`allow_mutations=true` ke environment privat. Baca payload dan Docs dahulu.
Update Settings sengaja menggunakan issuer ilustratif `demo.example.invalid`;
ganti ke issuer yang Anda inginkan sebelum mengeksekusi karena JWT lama bisa ditolak.
Tidak ada proses rollback/restoration otomatis.

Create Customer memerlukan **DocType Customer** dari ERPNext atau app lain, izin
create, dan kelengkapan field wajib situs. Frappe + app ini saja tidak menyediakan
Customer. Contoh invalid email tetap bisa dijalankan dengan JWT tanpa Customer,
karena validasi menolak sebelum insert. Validator hanya memeriksa keberadaan `@`.

## Envelope respons

- RPC custom/JWT: `{"message": ...}`.
- Custom validation: HTTP 422 dengan `message._code`, `_detail`, `_status_code`.
- Authentication/framework error: HTTP 401/403 dan `exc_type`/`exception`.
- Resource/document-method Frappe v1: `{"data": ...}`. Clear logs mengembalikan
  `data` numerik sesuai return controller; bukan objek token atau message.

Setiap `.bru` menyertakan native `example { ... }` agar success/error illustration
tersedia langsung pada endpoint di Bruno, bukan hanya README ini.

## Generate HTML documentation

```bash
bru docs generate -o reports/index.html --no-git-link
```

File HTML standalone tersedia di `bruno/reports/index.html` setelah generation;
folder reports di-ignore. Jangan gunakan `--all-envs` saat berbagi dokumentasi
jika memiliki environment privat. Jika membuat run reports, hilangkan header dan
body agar token tidak ikut diekspor:

```bash
bru run Authentication --env Local --disable-cookies --bail \
  --reporter-json reports/auth.json --reporter-skip-all-headers --reporter-skip-body
```

Referensi: [Bruno CLI](https://docs.usebruno.com/bru-cli/run/overview.md),
[response examples](https://docs.usebruno.com/send-requests/res-data-cookies/response-examples.md).
