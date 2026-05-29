# Despliegue — fraude-back (Railway)

Guía para publicar el API en **Railway**. El frontend va en Vercel → ver `fraude-front/DEPLOY.md`.

## URLs de producción (referencia)

| Servicio | URL |
|----------|-----|
| API | https://fraude-back-production.up.railway.app |
| Swagger | https://fraude-back-production.up.railway.app/swagger |
| Health | https://fraude-back-production.up.railway.app/health |
| Front | https://fraude-front.vercel.app |

---

## Requisitos

- Cuenta en [Railway](https://railway.app)
- Base de datos **Neon** (PostgreSQL) con `DATABASE_URL`
- Proyecto Google Cloud **`fraudia`** con Gmail API y OAuth **Web**
- Node.js (para Railway CLI): `npm install -g @railway/cli`

---

## Primera vez

### 1. Login en Railway

```powershell
cd D:\work\fraude-back
railway login
```

### 2. Crear proyecto y desplegar

```powershell
.\scripts\railway-deploy.ps1 -Init
```

El script:

1. Crea el proyecto `fraude-back` (solo con `-Init`)
2. Sube variables desde `.env.despliegue`
3. Ejecuta `railway up` (Dockerfile + migraciones Alembic)

Si el proyecto **ya existe** pero no tiene servicio:

```powershell
railway add --service fraude-back
railway service link fraude-back
.\scripts\railway-deploy.ps1
```

### 3. Dominio público

Dashboard → servicio → **Settings → Networking → Generate Domain**

O:

```powershell
railway domain --service fraude-back
```

Anota la URL (ej. `https://fraude-back-production.up.railway.app`) y actualiza en `.env.despliegue`:

```env
APP_BASE_URL=https://fraude-back-production.up.railway.app
FRONTEND_URL=https://fraude-front.vercel.app
ALLOWED_ORIGINS=https://fraude-front.vercel.app
```

---

## Volumen persistente (Gmail)

Sin volumen, `token.json` y los PDFs **se pierden** en cada redeploy.

1. Railway Dashboard → servicio **fraude-back** → **Add Volume**
2. Mount path: `/data`
3. Variables (ya en `.env.despliegue`):

```env
GMAIL_TOKEN_FILE=/data/token.json
GMAIL_DOWNLOAD_DIR=/data/gmail_attachments
```

---

## Variables de entorno

Plantilla completa: **`.env.despliegue`** (no se sube a git).

| Variable | Descripción |
|----------|-------------|
| `APP_ENV` | `production` |
| `APP_BASE_URL` | URL pública del API en Railway |
| `FRONTEND_URL` | URL del front en Vercel (callback OAuth) |
| `ALLOWED_ORIGINS` | Orígenes CORS (URL del front) |
| `DATABASE_URL` | Neon con `?sslmode=require` |
| `GOOGLE_OAUTH_CREDENTIALS_JSON` | JSON del cliente OAuth **Web** (una línea) |
| `GMAIL_WATCH_TOPIC` | `projects/fraudia/topics/...` |
| `OPENAI_API_KEY` | Key de OpenAI |
| `GMAIL_TOKEN_FILE` | `/data/token.json` |
| `GMAIL_DOWNLOAD_DIR` | `/data/gmail_attachments` |

En producción el backend también acepta previews de Vercel (`https://*.vercel.app`) vía regex CORS.

### Subir variables manualmente

```powershell
Get-Content credentials.json -Raw | railway variable set GOOGLE_OAUTH_CREDENTIALS_JSON --stdin
railway variable set APP_BASE_URL=https://fraude-back-production.up.railway.app
railway variable set FRONTEND_URL=https://fraude-front.vercel.app
railway variable set "ALLOWED_ORIGINS=https://fraude-front.vercel.app"
```

---

## Google Cloud — OAuth Web

Cliente OAuth tipo **Aplicación web** (no Desktop).

### URIs de redireccionamiento autorizados

```
https://fraude-back-production.up.railway.app/api/v1/gmail/auth/callback
http://127.0.0.1:8000/api/v1/gmail/auth/callback
```

### Orígenes JavaScript (opcional)

```
https://fraude-front.vercel.app
http://localhost:3000
```

### Pub/Sub (watch Gmail en tiempo real)

```
https://fraude-back-production.up.railway.app/api/v1/webhooks/gmail/push
```

Tras crear el cliente Web, guarda el JSON como `credentials.json` y súbelo a Railway:

```powershell
Get-Content credentials.json -Raw | railway variable set GOOGLE_OAUTH_CREDENTIALS_JSON --stdin
railway redeploy --service fraude-back -y
```

Espera **5–10 minutos** para que Google aplique los cambios.

### Pantalla de consentimiento — permitir cualquier Gmail

Si los usuarios ven **403 access_denied** o *“only developer-approved testers”*, la app está en modo **Testing**.

1. **APIs y servicios** → **Pantalla de consentimiento de OAuth**
2. Completa: nombre, email de soporte, **política de privacidad** (URL pública obligatoria)
3. **Dominios autorizados**: `vercel.app`, `up.railway.app`
4. Pulsa **Publicar aplicación** (Testing → **In production**)

Alternativa rápida (máx. 100 usuarios): agrega emails en **Usuarios de prueba**.

Con scopes Gmail (`readonly`, `send`), Google mostrará *“Google hasn't verified this app”* hasta completar verificación oficial. Los usuarios pueden entrar con **Avanzado → Continuar**.

---

## Redeploy

```powershell
cd D:\work\fraude-back
.\scripts\railway-deploy.ps1              # variables + deploy
.\scripts\railway-deploy.ps1 -SkipVariables # solo código
```

Comandos útiles:

```powershell
railway logs --service fraude-back
railway service status --json
railway variable list --service fraude-back
railway redeploy --service fraude-back -y
```

---

## Despliegue automático (push a `main`)

Cada commit en `main` puede actualizar producción sin correr scripts a mano.

### Opción A — Recomendada: GitHub en Railway (sin Actions)

1. Repo: `https://github.com/Julius266/fraude-back`
2. [Railway Dashboard](https://railway.app) → proyecto **fraude-back** → servicio **fraude-back**
3. **Settings → Source → Connect Repo** → rama **`main`**
4. Activa **Deploy on push**

Flujo: `git push origin main` → Railway construye con el `Dockerfile` y despliega.

> Las variables de entorno siguen en Railway (`.env.despliegue` es plantilla local).

### Opción B — GitHub Actions

Archivo: `.github/workflows/deploy-railway.yml`

#### Paso obligatorio: crear `RAILWAY_TOKEN`

1. Abre [Railway → Account → Tokens](https://railway.app/account/tokens)
2. **Create token** → nombre ej. `github-actions-fraude-back` → copia el token (solo se muestra una vez)
3. Abre [GitHub → fraude-back → Secrets → Actions](https://github.com/Julius266/fraude-back/settings/secrets/actions)
4. **New repository secret**
   - Name: `RAILWAY_TOKEN`
   - Secret: pega el token de Railway
5. Push a `main` o re-ejecuta el workflow en **Actions → Deploy backend → Re-run jobs**

Desde terminal (si tienes `gh auth login`):

```powershell
gh secret set RAILWAY_TOKEN --repo Julius266/fraude-back
# pega el token cuando lo pida
```

Si usas **Opción A** (Connect Repo en Railway), desactiva o borra el workflow para no desplegar dos veces y **no necesitas** `RAILWAY_TOKEN`.

---

## Verificar que funciona

```powershell
Invoke-RestMethod https://fraude-back-production.up.railway.app/health
Invoke-RestMethod https://fraude-back-production.up.railway.app/api/v1/gmail/config
Invoke-RestMethod https://fraude-back-production.up.railway.app/api/v1/gmail/auth/status
```

Esperado:

- `/health` → `status: ok`
- `/gmail/config` → `gmail_oauth_redirect_uri` con URL de Railway
- `/gmail/auth/status` → `credentials_configured: true`

Prueba OAuth en el navegador: https://fraude-front.vercel.app/login

---

## Problemas frecuentes

### `Project has no services`

Crea y enlaza el servicio antes de variables:

```powershell
railway add --service fraude-back
railway service link fraude-back
.\scripts\railway-deploy.ps1
```

### `redirect_uri_mismatch` (Google)

El redirect del API no está en Google Cloud. Usa cliente **Web** y agrega la URI de Railway (sección OAuth arriba).

### CORS bloqueado desde Vercel

- Usa https://fraude-front.vercel.app (alias estable), o
- Confirma `APP_ENV=production` (acepta `*.vercel.app`), o
- Agrega la URL preview a `ALLOWED_ORIGINS`

### `GOOGLE_OAUTH_CREDENTIALS_JSON no es JSON valido`

Sube el JSON con stdin (evita cortes por comillas):

```powershell
Get-Content credentials.json -Raw | railway variable set GOOGLE_OAUTH_CREDENTIALS_JSON --stdin
```

### `credentials_configured: false`

Falta el JSON en Railway o el redeploy no corrió. Redeploy tras subir la variable.

---

## Docker local (opcional)

```powershell
docker build -t fraude-back .
docker run --rm -p 8000:8000 --env-file .env fraude-back
```

---

## Multi-usuario (aislamiento de cuentas)

Cada analista tiene su **propio token OAuth** en PostgreSQL (`gmail_oauth_tokens`), keyed por email.

- Conectar Gmail en un navegador **no** afecta la sesión de otro usuario.
- `/api/v1/gmail/auth/status` solo responde `connected: true` para el email del header `X-Analyst-Email`.
- Logout solo borra el token del usuario que cierra sesión.
- Los siniestros/correos ya se filtran por `owner_email` en BD.

El `token.json` legacy en disco se migra automáticamente a BD al arrancar (una sola vez).

---

## Archivos de despliegue

| Archivo | Uso |
|---------|-----|
| `Dockerfile` | Imagen Python + OCR/PDF |
| `railway.toml` | Build Docker + healthcheck |
| `scripts/railway-deploy.ps1` | Deploy automatizado |
| `scripts/start.sh` | Arranque local Docker (referencia) |
| `.env.despliegue` | Variables para Railway |
