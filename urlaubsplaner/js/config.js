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
  //
  // Sie steht hier offen und darf das auch: Wer sie hat, kommt damit an keine
  // Daten. Google lässt die Anmeldung nur von den Adressen zu, die in der
  // Konsole eingetragen sind, fragt vorher das Google-Konto des Nutzers und
  // gibt der Anwendung mit „drive.file“ ohnehin nur die Datei frei, die sie
  // selbst angelegt hat. Ein fremdes Konto bekäme also höchstens einen
  // eigenen, leeren Plan im eigenen Drive.
  googleClientId: '551536265948-341q43svao7m3im7seg2hkha55kbhk12.apps.googleusercontent.com',

  // Name der Datei, die im Drive angelegt wird.
  driveFileName: 'Urlaubsplaner.json',

};
