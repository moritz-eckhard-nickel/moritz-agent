# Stimme „Hans“ einrichten

Moritz will die Stimme **Hans**. Hans ist keine Datei, die man herunterladen kann, sondern eine
Stimme des Dienstes **Amazon Polly** – das ist die Sprachausgabe von Amazon Web Services (AWS),
dem Cloud-Anbieter von Amazon. Viele bekannte „Text-to-Speech“-Webseiten benutzen genau diese
Stimme. Für moritz-agent heißt das:

| | Hans (Amazon Polly) | Lokale Stimme (Piper „Thorsten“) |
| --- | --- | --- |
| Klang | genau die gewünschte Hans-Stimme | ähnlich neutral-männlich, aber nicht Hans |
| Läuft | in der Cloud bei Amazon | komplett im Agent-LXC |
| Braucht | Internet + AWS-Konto (Zugangsschlüssel) | nichts |
| Kosten | pro gesprochenem Zeichen; bei kurzen Telefonantworten Cent-Beträge im Monat | keine |
| Datenschutz | die **Antworttexte** des Agents gehen an Amazon (nie die Stimme des Anrufers) | alles bleibt lokal |

**Einstellung in moritz-agent:** Hans ist die Standardstimme (`[phone.tts] engine = "polly"`).
Fehlen die AWS-Schlüssel, ist das Internet weg oder antwortet Polly nicht innerhalb von 1,5 s,
spricht automatisch die lokale Stimme – der Anruf bricht nie ab (ADR-008). Die Begrüßung und
alle festen Ansagen werden beim Einrichten einmal mit Hans erzeugt und gespeichert; sie
klingen also auch ohne Internet nach Hans.

## Einrichten (einmalig, ca. 15 Minuten)

1. **AWS-Konto anlegen:** <https://aws.amazon.com> → „Konto erstellen“. Dafür werden E-Mail,
   Telefonnummer und eine Zahlungsmethode verlangt.
2. **Eigenen Benutzer nur für den Agent anlegen** (nie den Haupt-Login verwenden):
   AWS-Konsole → **IAM** → *Benutzer* → *Benutzer erstellen* → Name `m-agent-polly`,
   **kein** Konsolenzugriff.
3. **Nur die eine nötige Berechtigung geben:** beim Benutzer → *Berechtigungen hinzufügen* →
   *Inline-Richtlinie erstellen* → JSON:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       { "Effect": "Allow", "Action": "polly:SynthesizeSpeech", "Resource": "*" }
     ]
   }
   ```
   Damit kann der Schlüssel ausschließlich Sprache erzeugen – sonst nichts im AWS-Konto.
4. **Zugriffsschlüssel erstellen:** Benutzer → *Sicherheitsanmeldeinformationen* →
   *Zugriffsschlüssel erstellen* → Anwendungsfall „Anwendung, die außerhalb von AWS läuft“.
   Angezeigt werden **Access Key ID** und **Secret Access Key** (nur einmal sichtbar).
5. **In `passwords.txt` eintragen** (Abschnitt `[optional_services]`) – oder einfach den
   Installer fragen lassen:
   ```ini
   [optional_services]
   aws_polly_access_key_id = AKIA…
   aws_polly_secret_access_key = …
   aws_polly_region = eu-central-1
   ```
   `eu-central-1` ist Frankfurt.
6. **Übernehmen:** Reload in der Web-UI (oder `systemctl reload moritz-agent`). Die Statusseite
   zeigt danach „TTS: Hans (Amazon Polly) bereit“; die Ansagen werden neu erzeugt.
7. **Kostenbremse (empfohlen):** AWS-Konsole → *Billing* → *Budgets* → Budget mit z. B. 5 €
   pro Monat und E-Mail-Warnung anlegen.

## Kosten grob

Polly berechnet Standard-Stimmen pro Million Zeichen (aktueller Preis: AWS-Preisseite für
Amazon Polly). Eine Telefonantwort hat meist 80–200 Zeichen. Beispiel: 100 Antworten am Tag
≈ 450.000 Zeichen im Monat – das liegt im Bereich von wenigen Euro oder darunter.

## Wenn es nicht klappt

| Statusmeldung | Ursache | Lösung |
| --- | --- | --- |
| „Polly: Zugriff verweigert“ | Richtlinie fehlt oder falscher Schlüssel | Schritt 3/4 prüfen |
| „Polly: Region ungültig“ | Tippfehler in `aws_polly_region` | `eu-central-1` |
| „Polly: Zeitüberschreitung – lokale Stimme aktiv“ | kein Internet | Internet prüfen; Gespräche laufen mit Thorsten weiter |
