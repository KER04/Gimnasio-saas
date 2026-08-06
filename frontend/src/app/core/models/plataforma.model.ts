/**
 * Panel del PROVEEDOR (`/api/plataforma/`), no de un gimnasio.
 *
 * Es otro sistema con otra identidad: aquí no hay tenant, ni sede, ni
 * permisos de gimnasio. Un empleado del proveedor ve todos los gimnasios;
 * un usuario de gimnasio no entra aquí en absoluto.
 */

export type RolPlataforma = 'administrador' | 'soporte';

/** Ciclo de vida del contrato de un gimnasio. */
export type EstadoTenant = 'prueba' | 'activo' | 'mora' | 'suspendido' | 'cancelado';

export interface UsuarioPlataforma {
  id: number;
  nombre: string;
  correo: string;
  rol: RolPlataforma;
  activo: boolean;
  creado_en: string;
}

export interface RespuestaLoginPlataforma {
  access: string;
  refresh: string;
  usuario: UsuarioPlataforma;
}

/**
 * Fila del listado de gimnasios.
 *
 * No trae `id`: hacia fuera un gimnasio se identifica por `uuid_publico`,
 * para que las URLs no permitan enumerar la cartera contando 1, 2, 3.
 */
export interface TenantResumen {
  uuid_publico: string;
  nombre_comercial: string;
  subdominio: string;
  estado: EstadoTenant;
  ciudad: string | null;
  responsable: string;
  correo: string;
  fecha_alta: string;
  sedes: number | null;
  usuarios: number | null;
  clientes: number | null;
  membresias_activas: number | null;
  ultima_venta: string | null;
}

export interface SuscripcionResumen {
  id: number;
  plan_nombre: string;
  precio_por_sede: string;
  ciclo: 'mensual' | 'anual';
  fecha_inicio: string;
  fecha_fin: string | null;
  proximo_corte: string;
  dias_gracia: number;
  estado: 'vigente' | 'mora' | 'cancelada';
}

/** Ficha completa: añade configuración y contrato. */
export interface TenantDetalle extends TenantResumen {
  nit: string | null;
  telefono: string | null;
  logo_url: string | null;
  zona_horaria: string;
  moneda: string;
  dias_aviso_vencimiento: number;
  minutos_antipassback: number;
  fecha_cancelacion: string | null;
  fecha_purga_datos: string | null;
  creado_en: string;
  actualizado_en: string;
  /** `null` si el gimnasio todavía no tiene contrato vigente. */
  suscripcion: SuscripcionResumen | null;
}

/** Un usuario de un gimnasio, visto desde el panel. Solo lo necesario para
 * poder restablecerle la contraseña sabiendo a quién. */
export interface UsuarioDeGimnasio {
  id: number;
  nombre: string;
  correo: string;
  rol: string;
  activo: boolean;
}

/** Resultado del rescate. `password` solo llega aquí y no se puede recuperar. */
export interface PasswordRestablecida {
  usuario: { id: number; nombre: string; correo: string };
  password: string;
  subdominio: string;
}

/** Cuerpo del alta. La contraseña NO se manda: la genera el servidor. */
export interface TenantNuevo {
  nombre_comercial: string;
  subdominio?: string;
  correo_admin: string;
  nombre_sede?: string;
  responsable?: string;
  telefono?: string;
  ciudad?: string;
  nit?: string;
}

/**
 * Credenciales del gimnasio recién creado.
 *
 * `password` es la ÚNICA vez que esa contraseña existe fuera de su hash: no
 * se guarda en claro ni se puede volver a consultar. Si se pierde, se
 * restablece.
 */
export interface AccesoInicial {
  url: string;
  correo: string;
  password: string;
  sede: string;
}

export interface TenantCreado extends TenantDetalle {
  acceso_inicial: AccesoInicial;
}

/** Campos editables de la ficha. Ni `subdominio` ni `estado`: el primero es
 * la URL del cliente y el segundo tiene su propia acción con confirmación. */
export interface TenantConfiguracion {
  nombre_comercial: string;
  responsable: string;
  correo: string;
  telefono: string | null;
  ciudad: string | null;
  nit: string | null;
  zona_horaria: string;
  moneda: string;
  dias_aviso_vencimiento: number;
  minutos_antipassback: number;
}

export const ETIQUETAS_ESTADO_TENANT: Record<EstadoTenant, string> = {
  prueba: 'En prueba',
  activo: 'Activo',
  mora: 'En mora',
  suspendido: 'Suspendido',
  cancelado: 'Cancelado',
};

export const OPCIONES_ESTADO_TENANT: { valor: EstadoTenant | ''; etiqueta: string }[] = [
  { valor: '', etiqueta: 'Todos los estados' },
  { valor: 'prueba', etiqueta: 'En prueba' },
  { valor: 'activo', etiqueta: 'Activo' },
  { valor: 'mora', etiqueta: 'En mora' },
  { valor: 'suspendido', etiqueta: 'Suspendido' },
  { valor: 'cancelado', etiqueta: 'Cancelado' },
];
