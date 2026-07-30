# Gimnasio SaaS

Plataforma multi-tenant de gestión para gimnasios. Una sola aplicación y una sola
base de datos que se renta por suscripción: cada gimnasio contratante es un
*tenant* aislado que no puede ver los datos de ningún otro.

- **Backend:** Django 6 + Django REST Framework + PostgreSQL 16
- **Frontend:** Angular 20 (standalone, SCSS)
- **Autenticación:** JWT, con el tenant firmado dentro del token

El documento de requerimientos y el esquema PostgreSQL de referencia se
mantienen fuera del repositorio, como material de trabajo interno. La verdad
ejecutable del modelo de datos son las migraciones de Django.

---

## Aislamiento entre tenants

Es el requisito crítico del proyecto y se sostiene sobre tres capas:

1. **`tenant_id` en toda tabla de negocio**, con claves únicas compuestas
   (`UNIQUE(tenant_id, cedula)`) y **61 claves foráneas compuestas**
   `(hijo_id, tenant_id) → (padre.id, padre.tenant_id)`, que impiden a nivel de
   motor que una fila referencie a un padre de otro gimnasio.
2. **Row Level Security de PostgreSQL** con `FORCE` sobre 35 tablas. La
   aplicación se conecta con un rol **sin privilegios y sin `BYPASSRLS`**, así
   que las políticas le aplican de verdad.
3. **Middleware** que fija `app.tenant_id` dentro de la transacción de cada
   petición. El tenant sale del **JWT firmado**, no de datos que controle el
   cliente.

Las tres capas están cubiertas por pruebas automatizadas.

---

## Puesta en marcha

### Requisitos

- Python 3.12, Node 20+, Docker

### Base de datos

```bash
docker run -d --name gimnasio-db \
  -e POSTGRES_DB=gimnasio -e POSTGRES_PASSWORD=<clave> \
  -p 5432:5432 postgres:16
```

> El puerto 5432 debe estar libre. Si tienes un PostgreSQL nativo corriendo,
> detenlo (`sudo systemctl stop postgresql`) o publica el contenedor en otro
> puerto.

Crea el rol de aplicación, **sin privilegios y sin `BYPASSRLS`** — es lo que
hace que el aislamiento sea real:

```sql
CREATE ROLE app_user LOGIN PASSWORD '<clave>' NOSUPERUSER NOBYPASSRLS CREATEDB;
```

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # y rellena los valores
python manage.py migrate --database=ddl
python manage.py test
```

`DATABASES` tiene dos conexiones deliberadamente separadas:

| Alias | Rol | Uso |
|---|---|---|
| `default` | sin privilegios | runtime de la aplicación — RLS le aplica |
| `ddl` | superusuario | solo migraciones |

**La aplicación nunca debe correr como superusuario**: los superusuarios de
PostgreSQL ignoran RLS incluso con `FORCE`.

### Crear el primer gimnasio

```bash
python manage.py crear_tenant \
  --nombre "Gimnasio X" --subdominio gimx \
  --correo admin@gimx.com --password <clave> \
  --sede "Sede Principal"
```

Siembra el tenant, la sede, los cuatro roles del sistema con sus permisos, los
catálogos base y el usuario administrador.

### Levantar

```bash
python manage.py runserver          # backend
cd ../frontend && npm install && npx ng serve
```

Accede por el subdominio del gimnasio, no por `localhost` a secas:

```
http://gimx.localhost:8000/admin/
```

El subdominio identifica al gimnasio en el login, porque **el correo es único
por tenant, no globalmente**: la misma persona puede trabajar en dos gimnasios
distintos. Si el frontend y el API están en hosts distintos, el gimnasio también
puede enviarse como campo `subdominio` en el cuerpo del login.

---

## Estructura

```
backend/apps/
├── core/            infraestructura multi-tenant: middleware, contexto de
│                    tenant, migración del esquema SQL, pruebas de aislamiento
├── autenticacion/   login, registro, refresh, JWT con claim de tenant
├── plataforma/      tenants, suscripciones, facturación (nivel proveedor)
├── organizacion/    sedes, roles, permisos, usuarios
├── clientes/        clientes, autorizaciones de datos, huellas
├── membresias/      planes y membresías
├── inventario/      productos, stock por sede, kardex
├── ventas/          ventas, pagos, abonos, gastos
├── asistencia/      registro de asistencias y check-in
├── entrenamiento/   medidas corporales, ejercicios, rutinas
└── auditoria/       bitácora particionada y vistas de negocio
```

## Pruebas

```bash
cd backend && python manage.py test
```

Incluye la batería de aislamiento entre tenants. Su validez se comprobó por
mutación: al retirar RLS, las pruebas fallan.
