# scripts/

Entwickler- und Messwerkzeuge (nicht Teil der Laufzeit):

| Skript | Ticket | Zweck |
| --- | --- | --- |
| `build-pjsip.sh` | P1-11 | PJSIP aus `third_party/pjproject` bauen, Python-Binding `pjsua2` in die Umgebung installieren |
| `setup-tts-venv.sh` | P1-10 | Umgebung `runtime/venv-tts` für die CosyVoice-Stimme (torch CPU) anlegen |
| `sip_testcall.py` | P1-11 | Skriptgesteuerter Test-Anrufer: spricht Sätze, misst Antwortzeiten, nimmt Nikitas Antworten auf |
| *(statt `bench_audio.py`)* | P1-10 | `./test-1.sh bench` misst STT und Stimmen |
| `bench_llm.py` | P1-02 | 40 deutsche Telefonfragen: Latenz, Tokens/s, Tool-Call-Validität |
