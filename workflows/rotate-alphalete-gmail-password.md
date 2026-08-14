# Cambiar la contraseña de alphaletereporting@gmail.com

Se puede hacer. Lo único que hay que entender: **los reportes no usan la
contraseña de la cuenta, usan una "app password" de 16 letras** guardada en cada
máquina. Google **borra esa llave** cuando cambiás la contraseña de la cuenta, y
ahí todos los reportes que mandan o leen correo se caen a la vez, en silencio.

El plan de abajo es cambiarla + reponer la llave en las 3 máquinas el mismo día.
Toma ~30 min.

## Cuándo hacerlo
Después de las **07:15 hora central**, cuando ya salieron los reportes de la
mañana (Org Board fill 06:35, post 07:05, link ~07:10). Nunca antes.

## Lo que se rompe hasta que repongas la llave

**Mandan correo** (todos leen el mismo archivo vía
`scheduled_6_days_out/email_send.py:157`):
Scheduled 6 Days Out · Captainship Reports · Org Sales Board email + su gate ·
Board Emails (Country + All Units) + su gate · Override / DD Bulletin · BOX Order
Log · Owners Call Reminder · Owner Showdown · SARA Down · **las notificaciones
del propio orquestador** (`day_orchestrator/notify.py`, `shared/hub_notify_email.py`:
checkpoint, mail final de la pasada, avisos de fallo) · Machine Digest ·
`document_builder` y `office_onboarding`.

**Leen el inbox por IMAP:**
Financial Report · Frontier Sunday del Org Report · Tableau Screenshots email
tracker · SCI Campaigns · Residential Rep Count.

**No dependen de la app password** (los mira aparte, ver paso 4): los tokens
OAuth de esa cuenta — Sheets (`oauth-token.json`, el que escribe TODOS los fills),
Gmail drafts (`gmail-token.json`), Contacts (`contacts-token.json`, los grupos de
distro) y Drive (`drive-token.json`, el que sube los PDF de los 4 gates de
revisión).

**No se tocan:** raffi127 (BG Check Sync y el roster de Fiber Owners usan
`gmail-app-password-raffi127`, otro archivo) · Tableau · AppStream · ownerville ·
Double Entry · Slack · Vantura.

## 1. Cambiar la contraseña y generar la llave nueva
En la cuenta: Seguridad → cambiar contraseña. Después, en la MISMA pantalla de
Seguridad → **Contraseñas de aplicaciones** → generar una nueva (requiere que la
verificación en 2 pasos siga activa). Son 16 letras en 4 grupos; los espacios no
importan, el código los saca.

## 2. Ponerla en las 3 máquinas

**Windows (la de Eve)** — PowerShell, reemplazando `LLAVE`:
```
Set-Content -Path "$HOME\.config\recruiting-report\gmail-app-password" -Value "LLAVE" -Encoding utf8 -NoNewline
```

**Lucy 1 y Lucy 2** — desde la Windows, por la cola:
```
python -m automations.day_orchestrator.mini_control --enqueue set_alphalete_app_password LLAVE --machine "Lucy 1"
python -m automations.day_orchestrator.mini_control --enqueue set_alphalete_app_password LLAVE --machine "Lucy 2"
```
La acción escribe el archivo y **verifica sola** logueando por SMTP (envío) y por
IMAP (lectura); el resultado dice cuál de las dos mitades quedó viva. Está en
`SECRET_ACTIONS`, así que el poller **borra la celda de Args** apenas termina la
fila. Mientras la fila esté en cola, **no corras `--status`**: imprime la columna
Args entera, con la llave adentro.

La cola es serial: si hay un job colgado, estas filas esperan.

## 3. Probar que volvió
```
python -m automations.day_orchestrator.mini_control --enqueue ping --machine "Lucy 1"
```
y en la Windows, un envío y una lectura de verdad:
```
python -m automations.sara_down.run --dry-run
python -m automations.sci_campaigns.run --dry-run
```

## 4. Los tokens OAuth (revisar el mismo día)
Google revoca los refresh tokens **con scope de Gmail** al cambiar la contraseña.
Los de Sheets / Contacts / Drive normalmente sobreviven, pero hay que confirmarlo
porque si el de Sheets cayó **no se llena ninguna Sheet**:

| Token | Qué se lleva si cae | Cómo se repone |
|---|---|---|
| `oauth-token.json` (Sheets) | TODOS los fills | `python -m automations.recruiting_report.sheets_auth` en cada máquina |
| `gmail-token.json` (drafts) | drafts de captainship | `python -m automations.shared.gmail_auth` → `--enqueue set_gmail_token <json>` |
| `contacts-token.json` | los grupos de destinatarios | `python -m automations.shared.contacts_auth` → `set_contacts_ro_token` |
| `drive-token.json` | el PDF y el link de los 4 gates | `python -m automations.fiber_activations.drive_auth` → subirlo a mano |

Chequeo rápido de Sheets en las minis:
```
python -m automations.day_orchestrator.mini_control --enqueue sheets_whoami --machine "Lucy 1"
```

## 5. La sesión del navegador
El cambio de contraseña desloguea las sesiones abiertas, incluido el perfil
`sheets-browser-profile`. Hoy pega poco: captainship usa el camino sin login
(`sheet_render`, desde el 7/30) y `sheet_shot` quedó de respaldo. Si querés el
respaldo vivo, hay que reloguear **físicamente en la máquina** (2FA):
`python -m automations.captainship_drafts.sheet_shot login`.
