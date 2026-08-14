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

## 1. Cambiar la contraseña y generar las llaves nuevas
En la cuenta: Seguridad → cambiar contraseña. Después ir a
**myaccount.google.com/apppasswords** (requiere que la verificación en 2 pasos
siga activa). Se escribe un NOMBRE y se aprieta Create; salen 16 letras en 4
grupos, **una sola vez**. Los espacios no importan, el código los saca.

**No es una llave, son cuatro** — una por máquina/app, y así conviene dejarlo: la
columna "last used" de esa pantalla es cómo se ve qué máquina dejó de mandar
(estado al 2026-08-13):

| Nombre en Google | Quién la usa |
|---|---|
| `Alphalete Reporting Hub` | la Windows de Eve / el Hub |
| `Report's Mini` | Lucy 1 |
| `Lucy 2 Reports` | Lucy 2 |
| `Document Builder` | `document_builder` (config propia, ver su README) |

Regenerá una por nombre. **No borres las viejas con el tacho antes de tiempo** —
mientras la contraseña de la cuenta no cambió, siguen vivas y son el respaldo.
Después del cambio quedan muertas igual y se pueden borrar tranquilas.

Generar una llave nueva NO revoca las otras: por eso se puede ENSAYAR la rotación
entera (generar + instalar + verificar) sin tocar la contraseña de la cuenta.

## 2. Ponerla en las 3 máquinas

**Windows (la de Eve)** — PowerShell, reemplazando `LLAVE`:
```
Set-Content -Path "$HOME\.config\recruiting-report\gmail-app-password" -Value "LLAVE" -Encoding utf8 -NoNewline
```

**Lucy 1 y Lucy 2** — desde la Windows, por la cola. Si alguna de las dos no
bajó código desde el 2026-08-13, mandale primero un `--enqueue update` (Lucy 2
NUNCA actualiza sola): sin la acción nueva en su copia del repo, la fila vuelve
"unknown action".
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

## 2b. La cuarta llave: Document Builder (Streamlit Cloud)

**Esta no va en ninguna máquina** — por eso se escapa. El Document Builder es
`document_builder/` (en la RAÍZ del repo, no bajo `automations/`) y corre en
Streamlit Community Cloud, que guarda la llave en sus propios Secrets. No hay
`.streamlit/secrets.toml` local: Streamlit Cloud es el único lugar a tocar.

1. **share.streamlit.io** → iniciar sesión con la cuenta de GitHub dueña de
   `raffi127-ctrl/Alphalete-Reporting-Hub`.
2. La app cuyo "Main file path" es `document_builder/app.py` → **⋮ → Settings →
   Secrets**. (El `alphalete-orientation.streamlit.app` del README es un
   ejemplo, no el link real: al 2026-08-14 ese subdominio da "does not exist".
   El link verdadero es el que figura en el dashboard, y es el mismo que está
   en `app_url` dentro de los Secrets.)
3. En el bloque `[smtp]`, reemplazar sólo la línea `password`:
   ```toml
   password = "abcdefghijklmnop"
   ```
4. **Save.** La app se reinicia sola, ~1 minuto. El resto de los secretos
   (`access_code`, `admin_code`, `gcp_service_account`, `log_sheet_id`) no se
   tocan.

**Pegala sin espacios.** Google la muestra en 4 grupos de 4; el resto del Hub
los saca solo (`mini_control` hace `"".join(raw.split())`), pero este manda el
valor crudo a `srv.login()` (`document_builder/app.py:88`). Con espacios, falla.

**Cómo se ve rota mientras tanto:** el ICD igual descarga su PDF, pero le
aparece un `SMTPAuthenticationError` en pantalla y la copia BCC nunca llega a
alphaletereporting@ — de este lado no salta ninguna alerta. Distinto de
"email isn't configured (missing [smtp] secrets)", que es la llave FALTANTE.

**Probarla:** abrir el link con `?admin=1`, entrar con el `admin_code` y generar
un documento de prueba a tu propia dirección. Si el mail llega, quedó.

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
