/**
 * Usuarios del gimnasio (`/api/usuarios/`), detrás del permiso
 * `config.usuarios`.
 *
 * Un usuario NUNCA se borra: `Venta`, `Pago`, `Gasto` y los movimientos de
 * inventario lo protegen con PROTECT en la base de datos. Un recibo tiene
 * que poder decir quién lo hizo aunque esa persona ya no trabaje allí, así
 * que dar de baja es `activo=false`.
 */

export interface SedeDeUsuario {
  id: number;
  nombre: string;
}

export interface UsuarioGimnasio {
  id: number;
  nombre: string;
  correo: string;
  telefono: string | null;
  rol: number;
  rol_nombre: string;
  activo: boolean;
  sedes: SedeDeUsuario[];
  last_login: string | null;
  creado_en: string;
}

/** Alta. La contraseña NO se manda: la genera el servidor. */
export interface UsuarioFormulario {
  nombre: string;
  correo: string;
  telefono?: string;
  rol: number;
  sedes?: number[];
}

/** El correo no está: es la credencial con la que entra y no se edita. */
export interface UsuarioEdicion {
  nombre?: string;
  telefono?: string | null;
  rol?: number;
  sedes?: number[];
}

/**
 * Respuesta del alta y del restablecimiento.
 *
 * `password` es la ÚNICA vez que esa contraseña existe fuera de su hash: no
 * se guarda en claro ni se puede volver a consultar. Si se pierde, se
 * restablece.
 */
export interface UsuarioConPassword extends UsuarioGimnasio {
  password: string;
}

export interface RolGimnasio {
  id: number;
  nombre: string;
  descripcion: string | null;
  es_sistema: boolean;
  activo: boolean;
  permisos: number[];
}
