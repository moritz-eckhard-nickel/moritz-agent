# Die Weboberfläche

Adresse auf Sophie-1: **`https://192.168.1.187:3501`**. Sie ist nur im LAN erreichbar und hat einen Login.
Plan: [docs/plan/15-part2-umsetzung.md](plan/15-part2-umsetzung.md).

## Anmelden

- Benutzername und Passwort stehen in `passwords.txt` im Abschnitt `[web_login]`.
- Du bleibst **10 Tage** angemeldet, auch wenn moritz-agent neu startet (`server.session_ttl_hours = 240`).
- „Abmelden“ beendet die Sitzung auf diesem Gerät. Ändert sich Benutzername oder Passwort in
  `passwords.txt`, sind alle Geräte abgemeldet, auch wenn das passiert, während der Dienst aus ist.
- Nach 5 falschen Versuchen ist die Adresse 5 Minuten gesperrt.

## Zertifikat: keine Warnung im Browser

moritz-agent hat eine eigene kleine Zertifizierungsstelle (CA). Sie unterschreibt das Zertifikat der
Weboberfläche für alle eigenen IPs, den Hostnamen und `localhost`. Installierst du die CA **einmal** auf einem
Gerät, zeigt der Browser dort keine Warnung mehr. Das gilt auch, wenn später ein neues Server-Zertifikat
kommt (neue IP, Ablauf nach gut zwei Jahren): Es stammt von derselben CA.

1. Seite einmal öffnen und die Warnung wegklicken („Erweitert“ → „Weiter zu 192.168.1.187“).
2. **`https://192.168.1.187:3501/ca.crt`** aufrufen. Die Datei `m-agent-ca.crt` wird heruntergeladen.
3. Installieren:

| Gerät | So geht's |
| --- | --- |
| Windows | Doppelklick auf `m-agent-ca.crt` → „Zertifikat installieren“ → „Lokaler Computer“ → „Alle Zertifikate in folgendem Speicher speichern“ → **Vertrauenswürdige Stammzertifizierungsstellen** → Fertig. Browser neu starten. |
| Android | Einstellungen → Sicherheit → Weitere Sicherheitseinstellungen → Verschlüsselung und Anmeldedaten → **Zertifikat installieren** → **CA-Zertifikat** → Datei wählen. Chrome nutzt es danach. |
| iPhone/iPad | Datei öffnen → „Profil geladen“ → Einstellungen → Profil installieren. Danach Einstellungen → Allgemein → Info → **Zertifikatsvertrauenseinstellungen** → „moritz-agent CA“ einschalten. |
| macOS | Doppelklick → Schlüsselbundverwaltung → Zertifikat „moritz-agent CA“ öffnen → Vertrauen → **Immer vertrauen**. |
| Linux | `sudo cp m-agent-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`. Firefox: Einstellungen → Zertifikate → Importieren. |
| Firefox (alle Systeme) | Firefox hat einen eigenen Speicher: Einstellungen → Datenschutz & Sicherheit → Zertifikate anzeigen → Zertifizierungsstellen → **Importieren** → „Dieser CA vertrauen, um Websites zu identifizieren“. |

Weitere Adressen ins Zertifikat (zum Beispiel einen DNS-Namen) kommen über `server.public_hosts` in
`config/moritz-agent.toml`. Nach einem Neustart ist das neue Zertifikat da. Eigene IPs findet moritz-agent
selbst.

Wo die Dateien liegen: `runtime/tls/ca.pem` (CA, öffentlich), `runtime/tls/ca-key.pem` (privat, nur der
Dienst darf sie lesen), `runtime/tls/cert.pem` und `key.pem` (Server). Ein eigenes Zertifikat in
`server.tls_cert` wird nie angefasst.

**Wichtig:** `ca-key.pem` nie weitergeben. Wer sie hat, kann Zertifikate ausstellen, denen deine Geräte
vertrauen. Ist sie weg oder kompromittiert: `runtime/tls/` löschen, neu starten, die CA auf allen Geräten
neu installieren und die alte entfernen.

## Was es gibt

| Ansicht | Inhalt | seit |
| --- | --- | --- |
| Chat | mit Anton schreiben, Sofortauskünfte als Karten, Knöpfe für Rückfragen, Quellen. „Neues Gespräch“ leert sein Kurzzeitgedächtnis. | P2-01 |
| Status | alle Teile von moritz-agent mit Zustand, Konfiguration neu laden | P2-01 |

Streaming, Verlauf, Dateien, Einstellungen und die Modellseite kommen mit den nächsten Tickets.
