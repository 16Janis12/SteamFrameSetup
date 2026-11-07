# steamframe-setup

CLI-Tool für automatisierte Systemanpassungen und exaktes Undo für den **Valve Steam Frame Wireless-Dongle** (Treiber `rtw89`) und **VRLink / SteamVR** unter **CachyOS / Arch Linux**.

---

## Inhaltsverzeichnis
1. [Hintergrund & Zweck](#hintergrund--zweck)
2. [Architektur & Kernfunktionen](#architektur--kernfunktionen)
3. [Installation & Schnellstart](#installation--schnellstart)
4. [Befehlsreferenz & Optionen](#befehlsreferenz--optionen)
5. [Das Undo-System (Manifest & Backups)](#das-undo-system-manifest--backups)
6. [Problemfelder & Implementierungsdetails](#problemfelder--implementierungsdetails)
7. [Manuelle Checkliste (Nicht automatisierbar)](#manuelle-checkliste-nicht-automatisierbar)
8. [Verifikation & Bekannte Grenzen](#verifikation--bekannte-grenzen)

---

## Hintergrund & Zweck
Der Valve Steam Frame Wireless-Dongle arbeitet im Linux-Kernel als reguläres Wi-Fi-6E/7-Interface über den Realtek-Treiber `rtw89`. Das Headset spannt einen versteckten 6-GHz-VLP-Access-Point auf, mit dem sich der Dongle Punkt-zu-Punkt verbindet.

Auf Standard-Linux-Systemen (einschließlich CachyOS) treten dabei vier typische Hürden auf:
1. **Regulatorische Domäne (Regdom):** Domäne `00`/`UNDEF` sperrt das 6-GHz-Band oder drosselt die Sendeleistung drastisch (ca. 4 dBm).
2. **Firewall (UFW):** Die CachyOS-Standardeinstellung "deny incoming" blockiert Remote-Play-Handshake, Discovery und VRLink-Streaming stillschweigend.
3. **Latenzspitzen & Wi-Fi-Powersave:** Hintergrundscans von NetworkManager/wpa_supplicant sowie aktivierter Stromsparmodus verursachen periodische Spikes von 12 ms auf über 400 ms.
4. **SteamVR/Steam-Client:** Ein Watchdog versucht fälschlicherweise eine 32-Bit-`driver_vrlink`-Komponente zu starten; zudem erfordert VRLink erzwungenes PipeWire.

`steamframe-setup` löst diese Punkte idempotent, sicher und mit einem **lückenlosen Undo-Mechanismus**.

---

## Architektur & Kernfunktionen

Das Tool ist als eigenständiges Python-3-Skript (ausschließlich Python-Standardbibliothek, keine Fremdpakete) realisiert:

- **Sicher gegen Fehlkonfiguration:**
  - Erkennt die Dongle-Schnittstelle dynamisch anhand des Treibers `rtw89` (`/sys/class/net/*/device/driver`).
  - Schützt interne WLAN-Karten (z. B. MediaTek `mt7921e`, Intel `iwlwifi`) zuverlässig vor versehentlichen Änderungen.
  - Prüft vorab, welche Firewall tatsächlich aktiv ist (`ufw`, `firewalld`, `nftables`, `none`) und ändert UFW-Regeln **nur**, wenn UFW installiert und aktiv ist.
  - Modifiziert **niemals** die System-Binärdatei `/usr/bin/steam`, sondern richtet einen unprivilegierten Wrapper unter `~/.local/bin/steam-frame` für `$SUDO_USER` ein.
- **Idempotent:** Mehrfache Ausführung (`apply`) verändert nichts am Systemzustand und erzeugt keine doppelten Einträge.
- **Exaktes Undo:** Protokolliert jede Aktion in `/var/lib/steamframe-setup/manifest.json`. Auf Knopfdruck (`undo`) wird das System bitgenau in den Ausgangszustand zurückversetzt.
- **Testbar & Dry-Run:** Unterstützt `--dry-run` und `--root <dir>` für risikofreie Simulationen und Tests gegen Fake-Roots.

---

## Installation & Schnellstart

### 1. Ausführbar machen
```bash
chmod +x steamframe-setup
```

### 2. Status & Diagnose prüfen (ohne Root möglich)
```bash
./steamframe-setup status
```

### 3. Simulation (Dry-Run)
```bash
./steamframe-setup apply --dry-run
```

### 4. Anpassungen anwenden
```bash
sudo ./steamframe-setup apply
```

### 5. Alle Änderungen exakt zurücknehmen
```bash
sudo ./steamframe-setup undo
```

---

## Befehlsreferenz & Optionen

```text
steamframe-setup [-h] [--version] [--dry-run] [--iface IFACE]
                 [--country COUNTRY] [--ufw-scope {iface,all}] [-y]
                 [--root ROOT] {apply,undo,status,check} ...
```

### Kommandos
| Kommando | Beschreibung |
|---|---|
| `apply` | Wendet alle Systemanpassungen an (Regdom, UFW, Powersave, NM-Dispatcher, Steam-Launcher). |
| `undo` | Nimmt alle vom Tool vorgenommenen Änderungen exakt anhand des Manifests zurück. |
| `status` | Analysiert den aktuellen Systemzustand (`angewendet / nicht angewendet / abweichend`). |
| `check` | Alias für `status` mit detaillierter Validierung. |

### Globale Optionen
| Flag | Standard | Beschreibung |
|---|---|---|
| `--dry-run` | `False` | Führt keine Schreiboperationen oder Systembefehle aus. Zeigt an, was passieren würde. |
| `--iface <name>` | `auto` | Spezifischer Interface-Name des Dongles (z. B. `wlan1`). Standardmäßig automatische Erkennung via `rtw89`. |
| `--country <CC>`| `DE` | 2-stelliger ISO-Ländercode für die Regulatorische Domäne. |
| `--ufw-scope` | `iface` | Scope der UFW-Regeln: `iface` (empfohlen: nur auf dem Dongle) oder `all` (systemweit). |
| `-y`, `--yes` | `False` | Bestätigt Sicherheitsabfragen automatisch (für Skripte / non-interactive). |
| `--root <dir>` | `/` | Basisverzeichnis für Dateisystemoperationen (für Tests / Chroot). |
| `--remove-packages` | `False` | Nur für `undo`: Deinstalliert auch durch das Tool installierte Pakete (z. B. `wireless-regdb`). |

---

## Das Undo-System (Manifest & Backups)

Jede durch `steamframe-setup apply` durchgeführte Systemanpassung wird in `/var/lib/steamframe-setup/manifest.json` protokolliert:

- **Dateibackups mit SHA256-Hash:** Existierende Dateien (z. B. `/etc/conf.d/wireless-regdom`) werden vor der Bearbeitung in `/var/lib/steamframe-setup/backups/` gesichert. Bei einem erneuten `apply` wird das Original-Backup nicht überschrieben.
- **Erstellte Dateien:** Neu angelegte Konfigurationen (`/etc/modprobe.d/steamframe-regdom.conf`, `/etc/NetworkManager/conf.d/99-steamframe-powersave.conf`, Dispatcher-Skripte, systemd-Units, Steam-Wrapper) werden lückenlos gelistet.
- **UFW-Regeln:** Die exakten Löschbefehle für jede hinzugefügte Regel werden hinterlegt. Bereits vorher vorhandene Firewall-Regeln bleiben unberührt.
- **Zustandswiederherstellung bei `undo`:**
  1. Hinzugefügte UFW-Regeln werden gelöscht; UFW wird neu geladen.
  2. Modifizierte Dateien werden aus dem Backup wiederhergestellt.
  3. Erstellte Dateien und systemd-Units werden gelöscht; systemd und NetworkManager werden neu geladen.
  4. Der ursprüngliche Regdom-Wert wird via `iw reg set` restauriert.
  5. Manifest und Backup-Verzeichnis werden restlos entfernt.
  6. Idempotent: Fehlt eine Datei oder Regel bereits, bricht `undo` nicht ab, sondern meldet den Zustand und fährt fort.

---

## Problemfelder & Implementierungsdetails

### 1. Regulatorische Domäne (Regdom)
- **Problem:** Bei Domäne `00` ist das 6-GHz-Band gesperrt oder die TX-Leistung auf ca. 4 dBm gedrosselt.
- **Lösung:**
  - Stellt das Paket `wireless-regdb` sicher (fragt bei Fehlen nach Installation via `pacman -S --needed`).
  - Schreibt persistent `WIRELESS_REGDOM="DE"` in `/etc/conf.d/wireless-regdom`.
  - **Fallback 1:** Hinterlegt `/etc/modprobe.d/steamframe-regdom.conf` mit `options cfg80211 ieee80211_regdom=DE`.
  - **Fallback 2:** Richtet die systemd-Oneshot-Unit `/etc/systemd/system/steamframe-regdom.service` ein.
  - Setzt sofort `iw reg set DE` und verifiziert das 6-GHz-Band (5945–6425 MHz) sowie etwaige self-managed PHYs per `iw reg get`.

### 2. Firewall (UFW)
- **Problem:** CachyOS nutzt standardmäßig UFW mit "deny incoming". Pairing und Streaming schlagen still fehl.
- **Lösung:**
  - Prüft, ob UFW aktiv ist. Ist eine andere Firewall (z. B. firewalld) oder keine Firewall aktiv, wird nichts geändert und ein Hinweis ausgegeben.
  - Schaltet die benötigten Ports mit Kommentar `steamframe-setup` frei:
    - `27031/udp` (Steam Remote Play Handshake)
    - `27036/udp` (Steam Remote Play Discovery)
    - `27036/tcp` (Steam Remote Play Sitzungssteuerung)
    - `27037/tcp` (Steam Streaming Kontrollkanal)
    - `10400/udp` (VRLink Videostrom, Recherche-Kandidat)
    - `10401/udp` (VRLink Rückkanal, Recherche-Kandidat)
  - Scope `iface` (Standard): `ufw allow in on <iface> to any port <port> proto <proto> comment "steamframe-setup"` schützt das restliche Netzwerk.

### 3. Latenzspitzen & Scan-Unterdrückung
- **Problem:** Wi-Fi-Powersave und zyklische Background-Scans von wpa_supplicant führen zu Rucklern und Latenzspitzen von bis zu 400 ms.
- **Warum `wpa_cli` unter NetworkManager oft versagt:**
  NetworkManager steuert `wpa_supplicant` standardmäßig über D-Bus an. Das klassische UNIX-Socket-Control-Interface ist häufig nicht aktiv oder nutzt zufällige Netzwerk-IDs.
- **Lösung:**
  - Persistentes Deaktivieren von Powersave via `/etc/NetworkManager/conf.d/99-steamframe-powersave.conf` (`wifi.powersave = 2`).
  - NetworkManager-Dispatcher-Skript `/etc/NetworkManager/dispatcher.d/99-steamframe.sh` setzt bei jedem Verbindungsaufbau (`up`, `dhcp4-change`) sofort `iw dev <iface> set power_save off` und versucht die `wpa_cli`-bgscan-Unterdrückung.
  - **Wichtigste Maßnahme gegen bgscan:** Sobald das Headset gekoppelt ist, sollte die Headset-BSSID im NetworkManager-Profil fixiert werden (siehe Checkliste).

### 4. Steam-Client & VRLink
- **Problem:** Der Watchdog versucht auf 64-Bit-Systemen fälschlich einen 32-Bit-`driver_vrlink` zu starten. Zudem blockiert Flatpak-Sandboxing Treiberpfade.
- **Lösung:**
  - Erstellt für den aktuellen Benutzer (`$SUDO_USER`) das Wrapper-Skript `~/.local/bin/steam-frame`:
    ```bash
    #!/usr/bin/env bash
    exec steam -pipewire -vrlinkforceenable "$@"
    ```
  - Erstellt den Desktop-Eintrag `~/.local/share/applications/steam-frame.desktop` ("Steam (Frame / VRLink)").
  - Warnung bei Flatpak-Steam: Es wird dringend die native Steam-Installation aus den CachyOS/Arch-Repos empfohlen.

---

## Manuelle Checkliste (Nicht automatisierbar)

Die folgenden Schritte müssen vom Nutzer manuell in der Benutzeroberfläche bzw. Konsole durchgeführt werden:

```text
================================================================================
                    MANUELLE CHECKLISTE (Nicht automatisierbar)
================================================================================
 1. BETA-KANAL AKTIVIEREN:
    - Steam-Client: Einstellungen -> Schnittstelle -> Beta-Teilnahme -> 'Steam Beta Update'
    - SteamVR: Bibliothek -> Rechtsklick auf SteamVR -> Eigenschaften -> Betas -> 'beta - SteamVR Beta Update'
    - Headset-OS: In den Systemeinstellungen des Headsets den Beta-Kanal aktivieren.

 2. STARTREIHENFOLGE BEACHTEN:
    - Zuerst Steam über 'steam-frame' (bzw. den Desktop-Eintrag 'Steam (Frame / VRLink)') starten.
    - SteamVR am Desktop starten.
    - Erst DANACH das Headset einschalten (der Dongle stellt eine direkte P2P-Verbindung her).

 3. BEI INSTABILITÄT / RUCKLERN:
    - SteamRT3 (Steam Linux Runtime 3.0) deaktivieren, falls Abstürze auftreten.
    - NetworkManager BSSID-Pinning: Sobald das Headset gekoppelt ist, die Headset-BSSID fest
      im NM-Verbindungsprofil hinterlegen:
      nmcli connection modify "<SSID>" 802-11-wireless.bssid "<HEADSET_MAC>"
      Dies stoppt periodische Roaming-Hintergrundscans in NetworkManager vollständig.
================================================================================
```

---

## Verifikation & Bekannte Grenzen

### Was verifiziert werden muss
1. **VRLink-Streaming-Ports 10400/10401 (UDP):**
   Diese Ports stammen aus Community-Messungen/Recherchen und sind von Valve noch nicht offiziell in der Dokumentation aufgeführt. Sie sind oben in `steamframe-setup` im Array `VRLINK_PORTS` als Konstanten definiert und können bei Bedarf angepasst werden.
2. **Self-Managed PHYs:**
   Manche Realtek-Module oder interne Wi-Fi-Karten nutzen Firmware-seitig festgelegte Frequenzbänder (`phy#X (self-managed)`). In diesem Fall erzwingt die Firmware ihre Region unabhängig von OS-Befehlen. Sollte 6 GHz gesperrt bleiben, muss das EEPROM/NVM des Dongles beachtet werden.
3. **Dongle-Hotplug ohne vorheriges Einstecken:**
   Wird `steamframe-setup apply` ohne eingesteckten Dongle ausgeführt, werden alle interface-unabhängigen Schritte (Regdom, Fallbacks, Steam-Launcher, NM-Konfiguration für `driver:rtw89*`) erfolgreich angewendet. Nach dem Einstecken des Dongles kann `sudo ./steamframe-setup apply` erneut aufgerufen werden, um die Interface-gebundenen UFW-Regeln zu finalisieren.

### Testsuite
Die integrierte Testsuite kann jederzeit ohne Root-Rechte ausgeführt werden:
```bash
python3 -m unittest discover tests
```
Alle 20 Unit-Tests decken Dongle-Erkennung, Firewall-Scoping, Regdom-Fallbacks, Latenz/Powersave, Steam-Launcher sowie die bitgenaue Manifest- und Undo-Wiederherstellung vollständig ab.
