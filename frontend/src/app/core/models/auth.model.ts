export interface Usuario {
  id: number;
  correo: string;
  nombre: string;
  rol: number;
  tenant_id: number;
  activo: boolean;
  creado_en: string;
}

export interface LoginRequest {
  correo: string;
  password: string;
  /**
   * Subdominio del gimnasio (tenant) en el que se busca al usuario. No es
   * una credencial: solo indica dónde buscar. Si se omite, el backend cae
   * al subdominio del Host de la petición como respaldo (ver
   * `AuthService.login` y `subdominioDesdeHostname`).
   */
  subdominio?: string;
}

export interface RegisterRequest {
  correo: string;
  nombre: string;
  password: string;
  rol: number;
  telefono?: string;
  /** Ver `LoginRequest.subdominio`. */
  subdominio?: string;
}

export interface AuthResponse {
  access: string;
  refresh: string;
  user: Usuario;
}

export interface RefreshResponse {
  access: string;
  refresh?: string;
}

/** Sede asignada al usuario (`GET /api/auth/me/` -> `sedes[]`). */
export interface Sede {
  id: number;
  nombre: string;
}

/** Resumen del tenant (gimnasio) del usuario, embebido en `me()`. */
export interface TenantResumen {
  id: number;
  nombre_comercial: string;
  subdominio: string;
}

/**
 * Contexto completo de la sesión, devuelto por `GET /api/auth/me/`
 * (`MeView`, ver `apps/autenticacion/views.py`). Los campos de `Usuario` van
 * en la raíz (compatibilidad con lo que ya existía); lo nuevo se añade al
 * lado: nombre del rol, resumen del tenant, sedes asignadas y códigos de
 * permiso del rol.
 *
 * `permisos` es SOLO para usabilidad (ocultar/mostrar acciones en la UI):
 * la autorización real la sigue imponiendo el backend con 403.
 */
export interface Sesion extends Usuario {
  rol_nombre: string | null;
  tenant: TenantResumen;
  sedes: Sede[];
  permisos: string[];
}
