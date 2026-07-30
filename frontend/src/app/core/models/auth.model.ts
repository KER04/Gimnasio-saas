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
