/**
 * Contrato de la capa de autenticación con el backend. Tipos planos, sin
 * lógica: lo que el API manda y lo que le mandamos.
 */

/** Cuerpo de `POST /api/auth/login/`. `subdominio` es opcional: solo hace
 * falta cuando no se puede deducir de la URL (ver `TenantService`). */
export interface LoginRequest {
  subdominio?: string;
  correo: string;
  password: string;
}

/** Sede a la que un usuario tiene acceso. */
export interface Sede {
  id: number;
  nombre: string;
}

/** Resumen del tenant embebido en la sesión (`GET /api/auth/me/`). */
export interface TenantResumen {
  id: number;
  nombre_comercial: string;
  subdominio: string;
}

/** Respuesta de `POST /api/auth/login/`. */
export interface AuthResponse {
  access: string;
  refresh: string;
  user: Usuario;
}

/** Respuesta de `POST /api/auth/refresh/`. El backend rota el refresh token:
 * puede o no devolver uno nuevo, por eso es opcional. */
export interface RefreshResponse {
  access: string;
  refresh?: string;
}

/** Usuario tal como viaja dentro de `AuthResponse`. */
export interface Usuario {
  id: number;
  correo: string;
  nombre: string;
  rol: number;
  tenant_id: number;
  activo: boolean;
  creado_en: string;
}

/** Respuesta completa de `GET /api/auth/me/`: el contexto de sesión que
 * usa toda la aplicación (permisos, sede, nombre del gimnasio, etc.). */
export interface Sesion extends Usuario {
  rol_nombre: string;
  tenant: TenantResumen;
  sedes: Sede[];
  permisos: string[];
}
