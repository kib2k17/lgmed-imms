# LGMED IMMS Android app

An installable APK that opens the LGMED IMMS website full-screen. The system
itself - Django, the database, the documents - stays on the server; the app is
only a window onto it, so every phone sees the same data and website updates
reach the app without reinstalling.

## Getting the APK

No Android Studio needed. GitHub builds it (`.github/workflows/build-apk.yml`):

1. Push a change under `mobile/` to `main`, or open the repository's
   **Actions** tab -> **Build APK** -> **Run workflow**.
2. When the run finishes (about 5 minutes), open it and download
   **lgmed-imms-apk** under *Artifacts*. Unzip it to get `app-debug.apk`.
3. Send the APK to the phone, tap it, and allow "Install unknown apps".

## First launch

The app asks for the server address. On the office network, start the server
with `.\run-lan.ps1` and enter the address it prints, e.g.
`http://192.168.1.10:8000`. The phone must be on the same Wi-Fi.

To change it later (for example once the system has a domain), long-press the
app icon -> **Change server address**. The same dialog appears whenever the
server can't be reached.

## Known limits

- **Each build is signed with a new throw-away key.** Installing a newer APK
  over an older one fails with "App not installed" - uninstall the old one
  first. A fixed signing key (kept in the repository's Actions secrets) fixes
  this and is needed before handing the app to real users.
- Downloads go through Android's download manager, so a file produced by a form
  submission (POST) rather than a link may not download inside the app.
- `usesCleartextTraffic` is on for the `http://` office-network server. Turn it
  off in `AndroidManifest.xml` once the system is served over `https://`.
