# Despliegue

Guía para poner el backend en producción (escrita contra Railway, pero vale
para Render, Fly o cualquier PaaS con PostgreSQL).

---

## Lo único que no puedes saltarte

**La aplicación necesita DOS roles de base de datos distintos.**

El aislamiento entre gimnasios no lo hace el código: lo hacen 35 políticas de
Row Level Security dentro de PostgreSQL. Y RLS tiene una regla que aquí es
letal: **un superusuario se las salta todas**, incluso con `FORCE ROW LEVEL
SECURITY`.

Railway (como casi todos) te da un único rol: `postgres`, que es superusuario.
Si `DB_APP_USER` apunta a él:

- la aplicación arranca sin quejarse,
- los tests pasan,
- todo *parece* funcionar,
- y **cada gimnasio ve los clientes, las ventas y la caja de todos los demás**.

No hay error ni aviso. Por eso `config/settings/prod.py` se niega a arrancar si
`DB_APP_USER` y `DB_DDL_USER` son el mismo rol.

### Crear el rol de la aplicación

Conéctate al Postgres del proveedor (en Railway: servicio Postgres → *Data* o
*Connect*) y ejecuta, **una sola vez**:

```sql
-- Rol SIN superusuario: RLS sí lo somete.
CREATE ROLE keradmin LOGIN PASSWORD 'pon-aqui-una-clave-larga';

GRANT CONNECT ON DATABASE railway TO keradmin;   -- ajusta el nombre de la BD
GRANT USAGE ON SCHEMA public TO keradmin;
```

Los permisos sobre las tablas se conceden **después de migrar**, porque las
tablas todavía no existen. Ver el paso 4.

---

## 1. Variables de entorno

Los nombres NO son los genéricos de un tutorial: este proyecto lee los suyos.
`SECRET_KEY` o `DATABASE_URL` a secas no hacen nada.

| Variable | Valor |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
| `DJANGO_SECRET_KEY` | una clave larga y aleatoria (ver abajo) |
| `DJANGO_ALLOWED_HOSTS` | tu dominio, p. ej. `miapp.up.railway.app` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://miapp.up.railway.app` |
| `DJANGO_CORS_ALLOWED_ORIGINS` | la URL del frontend, p. ej. `https://mifront.up.railway.app` |
| `DB_NAME` | `${{Postgres.PGDATABASE}}` |
| `DB_HOST` | `${{Postgres.PGHOST}}` |
| `DB_PORT` | `${{Postgres.PGPORT}}` |
| `DB_APP_USER` | `keradmin` |
| `DB_APP_PASSWORD` | la clave del `CREATE ROLE` de arriba |
| `DB_DDL_USER` | `${{Postgres.PGUSER}}` (el superusuario) |
| `DB_DDL_PASSWORD` | `${{Postgres.PGPASSWORD}}` |
| `REDIS_URL` | opcional pero recomendado, ver más abajo |

`DJANGO_ALLOWED_HOSTS` con `*` sirve para el primer arranque, pero déjalo con
el dominio real en cuanto lo tengas: con `*` cualquiera puede servir tu API
bajo su propio dominio y montar phishing con ella.

Generar la clave secreta:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

## 2. Start Command

```
gunicorn config.wsgi --log-file -
```

El módulo es `config`, no el nombre de la carpeta del repositorio.

> `manage.py` y `config/wsgi.py` traen `config.settings.dev` como valor por
> defecto. Si olvidas `DJANGO_SETTINGS_MODULE`, el despliegue arranca con la
> configuración de DESARROLLO **sin avisar**.

---

## 3. Migrar

Las migraciones crean extensiones, políticas RLS, tablas particionadas y
vistas: todo eso exige superusuario, así que van por la conexión `ddl`.

```bash
python manage.py migrate --database=ddl
python manage.py collectstatic --noinput
```

---

## 4. Permisos del rol de la aplicación

**Ahora sí**, ya con las tablas creadas:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO keradmin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO keradmin;

-- Para las tablas que se creen en el futuro (migraciones nuevas):
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO keradmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO keradmin;
```

### Comprobar que el aislamiento funciona de verdad

No lo des por hecho. Conéctate **como `keradmin`** (no como `postgres`) y:

```sql
SELECT count(*) FROM clientes;               -- debe devolver 0
SELECT set_config('app.tenant_id', '1', false);
SELECT count(*) FROM clientes;               -- ahora solo los del tenant 1
```

Si la primera consulta devuelve algo distinto de 0, **el rol se está saltando
RLS y no debes abrir el servicio al público**.

---

## 4-bis. Desplegar un cambio de base de datos

**`git push` NO aplica las migraciones.** Viajan en el repositorio como
archivos, pero el Start Command solo arranca `gunicorn`: nadie las ejecuta
por su cuenta. Si despliegas código que espera una columna nueva sin haber
migrado, la aplicación arranca y falla en la primera petición que la toque.

La forma robusta es el **Pre-deploy Command** de Railway (Settings → Deploy),
que corre ANTES de que la versión nueva empiece a recibir tráfico:

```
python manage.py migrate --database=ddl
```

`--database=ddl` no es opcional: las migraciones crean tablas, políticas RLS
y vistas, y eso exige el superusuario. La conexión de la aplicación
(`keradmin`) no tiene permisos para hacerlo, y debe seguir sin tenerlos.

### Comprobar qué hay aplicado

```bash
python manage.py showmigrations
```

Una migración con `[ ]` está en el código pero no en la base.

### Tablas nuevas y permisos

Si una migración futura crea una tabla, `keradmin` necesita permisos sobre
ella o la aplicación la verá como inexistente. El `ALTER DEFAULT PRIVILEGES`
del paso 4 ya lo cubre para todo lo que se cree DESPUÉS de haberlo
ejecutado; si lo saltaste, hay que repetir los `GRANT` tras cada migración
que añada tablas.

### Antes de migrar en producción

Las migraciones que solo AÑADEN cosas (una columna nueva que admite NULL,
una tabla) son seguras y reversibles. Las que borran o cambian el tipo de una
columna pueden perder datos y no se deshacen con un `git revert`: ahí conviene
un respaldo antes. Railway los ofrece en el servicio de Postgres.

---

## 5. Crear tu cuenta y el primer gimnasio

```bash
python manage.py crear_usuario_plataforma --nombre "Tu nombre" --correo tu@correo.com

python manage.py crear_tenant \
    --nombre "Gimnasio de prueba" --subdominio prueba \
    --correo admin@prueba.com --password 'una-clave-larga'
```

Omitir `--password` en el primero hace que se pida por consola, sin quedar en
el historial de bash. A partir de ahí, los gimnasios se dan de alta desde el
panel: `https://tu-frontend/plataforma/login`.

---

## 6. Caché compartida (importante con más de un worker)

Sin `REDIS_URL` se usa una caché **por proceso**, con tres consecuencias:

1. El límite de intentos de login pasa a ser "5 por minuto **por worker**".
2. Los contadores se reinician en cada despliegue.
3. **Suspender un gimnasio deja de ser inmediato**: `invalidar_cache_tenant`
   solo limpia el worker que atendió esa petición, así que el gimnasio
   suspendido sigue operando en los demás hasta que expire el TTL de 60 s.

Añade un servicio Redis y pon `REDIS_URL`, o arranca con `--workers 1`
mientras tanto.

---

## 7. Frontend

Es una aplicación Angular: se despliega como sitio estático, aparte.

**Antes de compilar, decide dónde vive el API.** `src/environments/environment.ts`
(el de producción) trae `apiUrl: '/api'`, que es una ruta **relativa**: asume
que el frontend y el backend se sirven desde el MISMO dominio. Si los
despliegas como dos servicios de Railway, cada uno tiene su dominio y el
frontend pediría `https://mifront.up.railway.app/api/...`, que no existe —
todas las peticiones darían 404.

Tienes dos opciones:

**a) Dominios separados** (lo más simple en Railway). Pon la URL absoluta:

```ts
export const environment = {
  production: true,
  apiUrl: 'https://mibackend.up.railway.app/api',
};
```

Y entonces `DJANGO_CORS_ALLOWED_ORIGINS` **es obligatorio**: el navegador
bloqueará las peticiones sin él.

**b) Un solo dominio**, con el frontend detrás del mismo host que el API. Deja
`apiUrl: '/api'` como está y CORS deja de importar. Requiere un proxy delante,
así que es más trabajo de infraestructura.

Después:

```bash
cd frontend && npx ng build
```

### Sobre los subdominios

El diseño previsto es que cada gimnasio entre por el suyo
(`gimx.midominio.com`) y el frontend lo deduzca de la URL. Eso necesita un
dominio propio con DNS comodín, que el dominio gratuito de Railway no da.

**Mientras tanto funciona igual**: si no hay subdominio en la URL, el login
muestra el campo "código de gimnasio" y el usuario escribe el suyo. A partir
del login el gimnasio viaja firmado dentro del JWT, así que nada más depende
del `Host`.

Cuando tengas dominio propio, añade el regex a
`DJANGO_CORS_ALLOWED_ORIGIN_REGEXES`:

```
^https://[a-z0-9-]+\.midominio\.com$
```

---

## Lista de comprobación

- [ ] Rol `keradmin` creado, distinto del superusuario
- [ ] `DB_APP_USER=keradmin`, `DB_DDL_USER=postgres`
- [ ] `SELECT count(*) FROM clientes` como `keradmin` devuelve **0**
- [ ] `DJANGO_SETTINGS_MODULE=config.settings.prod`
- [ ] `DJANGO_ALLOWED_HOSTS` con el dominio real, no `*`
- [ ] `migrate --database=ddl` aplicado
- [ ] `collectstatic` ejecutado
- [ ] `REDIS_URL` puesto, o `--workers 1`
- [ ] `apiUrl` del frontend apunta al backend (absoluta si son dominios distintos)
- [ ] `/api/auth/login/` responde y el admin se ve con estilos
