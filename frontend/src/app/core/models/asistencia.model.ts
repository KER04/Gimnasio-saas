import { ClienteResumen, MembresiaResumen } from './cliente.model';

/**
 * Contrato de asistencia (RF-15). **Sin biometría**: el lector todavía no
 * existe, así que `huella` no es un método válido.
 *
 * El flujo de recepción son dos pasos deliberadamente separados:
 *
 * 1. `GET /api/asistencias/verificar/?cedula=` — INFORMA y no registra nada.
 *    Es lo que se mira antes de dejar pasar.
 * 2. `POST /api/asistencias/` — registra el ingreso de verdad.
 *
 * Consultar no debe dejar rastro: mirar si alguien puede entrar no es lo
 * mismo que dejarle entrar.
 */

/** Métodos admitidos hoy (`Asistencia.MetodoAsistencia` en el backend). */
export type MetodoAsistencia = 'manual_cedula' | 'sesion_anonima';

/** Una asistencia registrada (`AsistenciaSerializer`). */
export interface Asistencia {
  id: number;
  sede: number;
  cliente: number | null;
  cliente_nombre: string | null;
  cliente_cedula: string | null;
  venta: number | null;
  metodo: MetodoAsistencia;
  fecha_hora: string;
  con_membresia_vigente: boolean;
  autorizado_por: number | null;
  autorizado_por_nombre: string | null;
  motivo_autorizacion: string | null;
}

/**
 * Respuesta del panel de verificación. Trae TODO lo que recepción necesita
 * para decidir en una sola pantalla: quién es, en qué estado están sus
 * membresías, si debe dinero y si el antipassback lo bloquea ahora mismo.
 */
export interface VerificacionAsistencia {
  cliente: ClienteResumen;
  /** TODAS sus membresías, no solo las vigentes: el panel también avisa de
   * las vencidas y las que están por vencer. */
  membresias: MembresiaResumen[];
  /** Texto, como el resto de importes. `"0"` si no debe nada. */
  saldo_pendiente: string;
  puede_ingresar: boolean;
  /** Inverso de `puede_ingresar`: sin membresía vigente el ingreso exige
   * autorización nominal (quién y por qué), no un simple visto bueno. */
  requiere_autorizacion: boolean;
  /** `true` si ya registró un ingreso dentro de la ventana configurada por
   * el gimnasio (`minutos_antipassback`). NO es un error: evita contar dos
   * veces la misma entrada. */
  bloqueado_por_antipassback: boolean;
  minutos_restantes_antipassback: number | null;
}

/** Cuerpo de `POST /api/asistencias/`. */
export interface RegistrarAsistenciaFormulario {
  metodo: MetodoAsistencia;
  /** Obligatoria con `manual_cedula`. */
  cedula?: string;
  /** Obligatoria con `sesion_anonima` (compra suelta sin membresía). */
  venta_id?: number;
  /** Obligatorios JUNTOS cuando el cliente no tiene membresía vigente. Quien
   * autoriza necesita el permiso `asistencia.autorizar`. */
  autorizado_por_id?: number;
  motivo_autorizacion?: string;
}
