/* ═══════════════════════════════════════════════════════════════════════
   config.js – Einstellungen für die Google-Drive-Anbindung

   Nur nötig, wenn der Plan in Google Drive liegen soll. Ohne Eintrag hier
   läuft der Planer wie gewohnt im Browser oder über den eigenen Server.

   Die Kennung stammt aus der Google Cloud Console und ist keine geheime
   Angabe – sie darf offen im Quelltext stehen. Wer sie hat, kann damit
   nichts anfangen: Google fragt vor jedem Zugriff das Google-Konto des
   Nutzers und lässt nur die Adressen zu, die dort eingetragen sind.

   Schritt-für-Schritt-Anleitung: siehe CLOUD-EINRICHTEN.md
   ═══════════════════════════════════════════════════════════════════════ */

window.UP_CONFIG = {

  // Die „Client-ID“ aus der Google Cloud Console. Sieht aus wie:
  // '1234567890-abcdefghijklmnop.apps.googleusercontent.com'
  googleClientId: '',

  // Name der Datei, die im Drive angelegt wird.
  driveFileName: 'Urlaubsplaner.json',

};
