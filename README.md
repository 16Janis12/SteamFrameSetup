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

### 5. Hängende SteamVR-Prozesse beenden (bei Verbindungsstörungen)
```bash
./steamframe-setup reset-steam
```

### 6. Alle Änderungen exakt zurücknehmen
```bash
sudo ./steamframe-setup undo
```

---

## Befehlsreferenz & Optionen

```text
steamframe-setup [-h] [--version] [--dry-run] [--iface IFACE]
                 [--country COUNTRY] [--ufw-scope {iface,all}] [-y]
                 [--root ROOT] {apply,undo,status,check,reset-steam} ...
```

### Kommandos
| Kommando | Beschreibung |
|---|---|
| `apply` | Wendet alle Systemanpassungen an (Regdom, UFW, Powersave, NM-Dispatcher, Steam-Launcher). |
| `undo` | Nimmt alle vom Tool vorgenommenen Änderungen exakt anhand des Manifests zurück. |
| `status` | Analysiert den aktuellen Systemzustand (`angewendet / nicht angewendet / abweichend`). |
| `check` | Alias für `status` mit detaillierter Validierung. |
| `reset-steam` | Beendet alle laufenden und hängenden Steam- und SteamVR-Prozesse (`vrserver`, `vrcompositor`, `steam`). |

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
  - Scope `iface` (Standard): `ufw allow in on <iface> to any port <port> proto <proto> comment "steamframe-setup"` schützt das restliche Netzwerk. Bei Mehrfach-WLAN-Systemen werden alle potenziell wechselnden Schnittstellen (`wlan0`, `wlan1`) abgedeckt.

### 3. Dynamische Hardware-Erkennung & Schutz vor Interface-Swapping (`wlan0` vs `wlan1`)
- **Problem (Race-Condition beim Boot):** Auf Systemen mit interner WLAN-Karte (z. B. MediaTek MT7922 / `mt7921e` via PCIe) und externem USB-Dongle initialisieren Kernel-Treiber asynchron und parallel. Je nachdem, ob PCIe oder USB zuerst fertig initialisiert, erhält der Dongle beim Booten `wlan0` oder `wlan1`.
- **Lösung in steamframe-setup:**
  1. **Eindeutige Hardware-Erkennung via USB VID/PID (`28de:2432`):** `DongleDetector` traversiert den Sysfs-Gerätebaum und identifiziert den Valve Steam Frame Dongle unfehlbar über Vendor-ID `28de` (Valve Corporation) und Product-ID `2432`.
  2. **Automatischer Schutz interner WLAN-Karten:** Interne PCIe-Karten (`mt7921e`, `iwlwifi`, etc.) werden erkannt, im Status angezeigt und strikt von Toggles und Modifikationen ausgenommen.
  3. **Treiber- und MAC-basiertes NetworkManager-Powersave:** Die NM-Konfiguration `/etc/NetworkManager/conf.d/99-steamframe-powersave.conf` matcht dynamisch über `driver:rtw89_8852cu;...;mac:<MAC>` statt starr über `interface-name:wlan0`.
  4. **Dynamischer NM-Dispatcher:** `/etc/NetworkManager/dispatcher.d/99-steamframe.sh` prüft bei jedem Netzwerk-Event (`up`, `down`) über Sysfs, ob das aufgerufene Interface zur `rtw89`-Familie gehört oder die USB-ID `28de:2432` trägt. Interne Karten werden ignoriert.
  5. **Swapping-sichere Firewall-Regeln:** Bei Scope `iface` werden Portfreigaben für alle relevanten Wireless-Interfaces hinterlegt, sodass VRLink-Traffic nach einem Reboot auch bei getauschten Interface-Namen ungehindert passiert.

### 4. Latenzspitzen & Scan-Unterdrückung
- **Problem:** Wi-Fi-Powersave und zyklische Background-Scans von wpa_supplicant führen zu Rucklern und Latenzspitzen von bis zu 400 ms.
- **Warum `wpa_cli` unter NetworkManager oft versagt:**
  NetworkManager steuert `wpa_supplicant` standardmäßig über D-Bus an. Das klassische UNIX-Socket-Control-Interface ist häufig nicht aktiv oder nutzt zufällige Netzwerk-IDs.
- **Lösung:**
  - Persistentes Deaktivieren von Powersave via `/etc/NetworkManager/conf.d/99-steamframe-powersave.conf` (`wifi.powersave = 2`).
  - NetworkManager-Dispatcher-Skript `/etc/NetworkManager/dispatcher.d/99-steamframe.sh` setzt bei jedem Verbindungsaufbau (`up`, `dhcp4-change`) sofort `iw dev <iface> set power_save off` und versucht die `wpa_cli`-bgscan-Unterdrückung.
  - **Wichtigste Maßnahme gegen bgscan:** Sobald das Headset gekoppelt ist, sollte die Headset-BSSID im NetworkManager-Profil fixiert werden (siehe Checkliste).

### 4. Valve Holo Realtek Firmware Toggles (SteamOS Low-Latency Integration)
Aus dem SteamOS/Holo-Repository von Valve (`sabae@valvesoftware.com`) stammt das Paket `holo-realtek-firmware-toggles`, das speziell für Steam Frame und `rtw89` entwickelt wurde.
- **Warum das Paket auf Desktop-Systemen fehlte:** SteamVR/VRLink versucht dieses Tool unter SteamOS via Polkit aufzurufen. Auf Standard-Distros wie CachyOS fehlt das Tool und die Polkit-Berechtigung, wodurch der Low-Latency-Modus fehlschlägt.
- **Was `set-low-latency-mode on` bewirkt (Gehärtete Fassung):**
  1. `HW_SCAN off`: Schaltet das Hardware-Hintergrundscanning im Realtek-DebugFS (`disable_dm`) aus – die eigentliche Ursache für periodische 400-ms-Spitzen!
  2. `set-amsdu off`: `iw dev <if> set tidconf tids 0xff amsdu off` umgeht einen bekannten Treiber-Bug bei A-MSDU-Aggregation im Realtek-Treiber.
  3. `set-powersave off`: Deaktiviert Host-Powersave und Firmware-seitiges `INACTIVE_PS`.
  4. `set-pd-thresh -75`: Setzt den Packet-Detection-Threshold auf -75 dBm, um entfernte Störsignale zu ignorieren.
  5. **Kernel-Stabilitäts-Patch (Crash-Guard):** `set-mcs-rates` via `iw dev ... set bitrates` ist im Skript neutralisiert, da es im Linux-Kernel-Treiber `rtw89_core` (`rtw89_phy_rate_pattern_vif`) zuverlässig eine fatale NULL-Pointer-Dereferenzierung mit IRQ-Lockout auslöst. Wi-Fi 6 handelt MCS-Raten dynamisch stabil aus.
  6. **Interface-Filter (Valve Issue #2983 Fix):** Filtert `p2p-dev-*`-Interfaces zuverlässig heraus, wodurch Fehlerausstiege und ungedrosselte `pkexec`-Dauerschleifen des Steam-Clients verhindert werden.
  7. **EDCA-Bereinigung:** Direktes Beschreiben von DebugFS-Registern (`c300`–`c30c`) entfällt, da EDCA-Werte AP-seitig von SteamVR/Hostapd gesetzt werden.
- **Integration in steamframe-setup:**
  - Installiert `/usr/bin/holo-polkit-helpers/holo-realtek-firmware-toggles` und die Polkit-Action `/usr/share/polkit-1/actions/org.valve.holo-realtek-firmware-toggles.policy`.
  - Bindet den Aufruf an den NetworkManager-Dispatcher (`set-low-latency-mode on` bei Interface-Up, `reset` bei Interface-Down).
  - Volle Manifest-Registrierung und sauberes Zurücksetzen bei `undo`.

### 5. System-Tuning: USB-Power, Socket-Puffer, Polkit & Ananicy
Die Recherche und Analyse von Upstream-Issues (`ValveSoftware/SteamVR-for-Linux`) ergab vier weitere kritische Stellschrauben:
- **USB-Autosuspend (U3):** Udev-Regel `/etc/udev/rules.d/99-steamframe-usb-power.rules` bindet auf `28de:2432` (`power/control="on"`, `power/autosuspend="-1"`).
- **Driver Powersave (`rtw89_core`):** `/etc/modprobe.d/steamframe-rtw89.conf` mit `options rtw89_core disable_ps_mode=y`.
- **Netzwerk-Socket-Puffer (Sysctl):** `/etc/sysctl.d/99-steamframe-network.conf` hebt `rmem_max`/`wmem_max` auf 32 MB an und nutzt `-net.core.netdev_max_backlog = 10000` (container- und namespace-sicher), um VRLink UDP-Pufferüberläufe (*"FAULT: Packet too big"*) zu verhindern.
- **Targeted Polkit Rule:** `/etc/polkit-1/rules.d/99-steamframe-networkmanager.rules` erlaubt unprivilegierten SteamVR-Sitzungen das Anlegen von P2P-Verbindungen (`settings.modify.system`, `network-control`, `wifi.share.protected`), ohne Sicherheitsrisiken einer pauschalen Freigabe.
- **Prozess-Priorisierung (Ananicy-cpp):** `/etc/ananicy.d/99-steamframe-vr.rules` priorisiert `vrcompositor` als `LowLatency_RT`, damit anspruchsvolle Proton-Spiele die Head-Tracking-Präsentation nicht aushungern.

### 6. Steam-Client, PipeWire, QT/Wayland & VRLink
- **Problem:** Der Watchdog versucht auf 64-Bit-Systemen fälschlich einen 32-Bit-`driver_vrlink` zu starten. Zudem blockiert Flatpak-Sandboxing Treiberpfade, Audio kann knacken oder desynchronisieren, und unter Wayland-Umgebungen (KDE Plasma, Sway, Hyprland) stürzt das SteamVR-Dashboard ohne erzwungenes X11/xcb-Backend still ab.
- **Lösung:**
  - Erstellt für den aktuellen Benutzer (`$SUDO_USER`) das Wrapper-Skript `~/.local/bin/steam-frame`:
    ```bash
    #!/usr/bin/env bash
    export PIPEWIRE_LATENCY="512/48000"
    export QT_QPA_PLATFORM="xcb"
    exec steam -pipewire -vrlinkforceenable "$@"
    ```
    (Setzt PipeWire-Quantumpuffer auf 10.66 ms gegen Audio-Knacken/Desync und erzwingt das stabile `xcb`-Backend für SteamVR).
  - Erstellt den Desktop-Eintrag `~/.local/share/applications/steam-frame.desktop` ("Steam (Frame / VRLink)").
  - Warnung bei Flatpak-Steam: Es wird dringend die native Steam-Installation aus den CachyOS/Arch-Repos empfohlen.

---

## Manuelle Checkliste (Nicht automatisierbar)

Die folgenden Schritte müssen vom Nutzer manuell in der Benutzeroberfläche bzw. Konsole durchgeführt werden:

```text
================================================================================
                    MANUELLE CHECKLISTE (Nicht automatisierbar)
================================================================================
 1. BETA-KANAL & OPENXR-LAUFZEIT:
    - SteamVR: Bibliothek -> Rechtsklick auf SteamVR -> Eigenschaften -> Betas -> 'beta - SteamVR Beta Update'
    - Steam-Client: Einstellungen -> Schnittstelle -> Beta-Teilnahme -> 'Steam Beta Update'
      (Tipp aus Steam-Guide: Falls die Steam-Client-Beta instabil ist, Client auf 'Standard/Stable' belassen und nur SteamVR auf 'Beta'!)
    - Headset-OS: In den Systemeinstellungen des Headsets den Beta-Kanal aktivieren.
    - OpenXR-Laufzeitumgebung: In den SteamVR-Einstellungen -> OpenXR -> 'SteamVR als aktive OpenXR-Laufzeitumgebung verwalten'
      (Wichtig: Verhindert, dass Titel wie VRChat im 2D-Flachbildmodus oder mit Xbox-Controller-Belegung starten).

 2. DESKTOP-AUTO-CONNECT (KDE Plasma / GNOME):
    - In den Netzwerkeinstellungen der Desktop-Umgebung prüfen, dass der Dongle sich NICHT automatisch mit dem Heim-WLAN verbindet.
      (KDE Plasma versucht sonst, bekannte Netzwerke über den Dongle zu verbinden und blockiert den P2P-Link für SteamVR).

 3. STARTREIHENFOLGE & HEADSET-BEDIENUNG:
    - Zuerst Steam über 'steam-frame' (bzw. den Desktop-Eintrag 'Steam (Frame / VRLink)') starten.
    - SteamVR am Desktop starten.
    - Erst DANACH das Headset einschalten.
    - Am Headset: Einstellungen -> Remote Play -> ganz nach unten zu 'Wireless Streaming Adapter' scrollen.
      Prüfen, ob der Adapter gekoppelt ist, und auf den Desktop klicken zum 'Pairen'.
    - Status-Icon in der Menüleiste am Headset prüfen:
      * GRÜN  = Nur Heim-WLAN verbunden.
      * LILA  = Multilink aktiv (Dongle und WLAN sind gleichzeitig verbunden - optimal!).
    - Streaming-Status am Headset: Host auswählen -> 'Erweitert' -> 'Stream VR Without Game' wählen!
      (Erst wenn SteamVR auf dem Headset läuft, das gewünschte VR-Spiel starten).

 4. BEI INSTABILITÄT, ABSTÜRZEN & VERBINDUNGSPROBLEMEN:
    - Hängende Prozesse beenden: Nach Abstürzen verbleiben oft 'vrserver' oder 'vrcompositor' im Hintergrund und blockieren
      Folgeverbindungen. Beenden mit: steamframe-setup reset-steam (oder: pkill -9 -f "steam|steamvr|vrserver")
    - Multilink-Option: In den SteamVR-Einstellungen (Erweitert aktivieren) -> Steam Link -> 'Allow Multiple Links'
      testweise umschalten, falls die Verbindung abbricht.
    - NetworkManager iwd-Backend: Falls mit wpa_supplicant kein P2P-Handshake zustande kommt,
      in /etc/NetworkManager/conf.d/ das iwd-Backend aktivieren ('wifi.backend=iwd', Paket: networkmanager-iwd).
    - SteamRT3 (Steam Linux Runtime 3.0): In SteamVR-Eigenschaften deaktivieren, falls Abstürze beim Streamstart auftreten.
    - NetworkManager BSSID-Pinning: Sobald das Headset gekoppelt ist, die Headset-BSSID fest
      im NM-Verbindungsprofil hinterlegen (nmcli connection modify <SSID> 802-11-wireless.bssid <BSSID>),
      um periodische Roaming-Hintergrundscans vollständig zu eliminieren.

 5. HARDWARE & USB-ANBINDUNG:
    - Dongle direkt an einen USB 3.0/3.2 Port am I/O-Panel der Mainboard-Rückseite anschließen.
    - Idealerweise ein 0.5–1m langes USB 3.0 Verlängerungskabel nutzen, um Abstand zu internen
      Mainboard-Antennen und 2.4/5 GHz Rauschen zu halten.
    - Falls Kernel-Bootparameter editierbar (GRUB / systemd-boot):
      'usbcore.quirks=28de:2432:k' deaktiviert USB 3.0 Link Power Management (LPM / U1/U2)
      für den Dongle vollständig und verhindert 50-100ms Micro-Stutters.

 6. HYBRID-GRAFIK & VULKAN-ENCODER (Laptops / APUs):
    - Bei Laptops mit iGPU + dGPU (NVIDIA/AMD) Steam mit DRI_PRIME=1 bzw. 'prime-run steam-frame' starten
      (verhindert PipeWire-Abstürze durch falsche DRI-Node-Zuordnung, Upstream-Bug #915).
    - SteamVR-Auflösung auf 'Auto' belassen (keine krummen Custom-Prozentwerte, Bug #965)
      und SteamVR Home deaktivieren, um 2 GB VRAM für den Vulkan-Video-Encoder zu reservieren.
================================================================================
```

---

## Verifikation & Bekannte Grenzen

### Was verifiziert werden muss
1. **VRLink-Streaming-Ports 10400/10401 (UDP):**
   Diese Ports stammen aus Community-Messungen/Recherchen und sind von Valve noch nicht offiziell in der Dokumentation aufgeführt. Sie sind oben in `steamframe-setup` im Array `VRLINK_PORTS` als Konstanten definiert und können bei Bedarf angepasst werden.
2. **Self-Managed PHYs & PASSIVE-SCAN Warnung:**
   Manche Realtek-Module oder interne Wi-Fi-Karten nutzen Firmware-seitig festgelegte Frequenzbänder (`phy#X (self-managed)`). In Valves Troubleshoot-Skript (`frame-dongle-troubleshoot.sh`) existiert zudem eine Warnung, wenn in `global` kein `PASSIVE-SCAN` steht; auf `phy#0` ist `PASSIVE-SCAN` bei gesetztem `DE` aktiv und unbedenklich.
3. **Dongle-Hotplug ohne vorheriges Einstecken:**
   Wird `steamframe-setup apply` ohne eingesteckten Dongle ausgeführt, werden alle interface-unabhängigen Schritte (Regdom, Fallbacks, Steam-Launcher, NM-Konfiguration, USB-Udev-Regel, Sysctl, Polkit) erfolgreich angewendet. Nach dem Einstecken des Dongles kann `sudo ./steamframe-setup apply` erneut aufgerufen werden, um die Interface-gebundenen UFW-Regeln zu finalisieren.

### Testsuite
Die integrierte Testsuite kann jederzeit ohne Root-Rechte ausgeführt werden:
```bash
python3 -m unittest discover tests
```
Alle 23 Unit-Tests decken Dongle-Erkennung, Firewall-Scoping, Regdom-Fallbacks, Latenz/Powersave, System-Tuning (USB/Sysctl/Polkit/Ananicy), Valve Holo Toggles, Steam-Launcher sowie die bitgenaue Manifest- und Undo-Wiederherstellung vollständig ab.
