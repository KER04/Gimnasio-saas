import { EstadoMembresia } from './cliente.model';

/**
 * Contrato de la asignación DIRECTA de membresía
 * (`POST /api/membresias/`, `AsignarMembresiaInputSerializer`).
 *
 * "Directa" significa sin pasar por caja: la membresía se crea con
 * `venta = NULL`. El camino normal de adquirir una membresía es venderla
 * (`POST /api/ventas/`, que ya la crea); esto cubre lo que no es una venta
 * -- cortesías, traspasos, correcciones administrativas -- y por eso el
 * backend lo deja registrado en auditoría.
 */
export interface AsignarMembresiaFormulario {
  cliente_id: number;
  plan_id: number;
  sede_id: number;
  /** `YYYY-MM-DD`. Si se omite, el backend usa la fecha de hoy del gimnasio. */
  fecha_inicio?: string;
  /** Texto, igual que el resto de importes (ver `precio.util.ts`). */
  precio_pagado: string;
  entrenador_id?: number | null;
}

/** Membresía tal como la devuelve la asignación (`MembresiaSerializer`). Solo
 * se declara lo que consume la ficha; el serializer devuelve bastante más. */
export interface MembresiaCreada {
  id: number;
  fecha_inicio: string;
  fecha_fin: string;
  estado: string;
}

/**
 * Cuerpo de `POST /api/membresias/{id}/renovar/`.
 *
 * La renovación NO modifica la membresía anterior: crea una nueva encadenada
 * a ella. La fecha de inicio la calcula el backend (RF-16): si la anterior
 * sigue vigente hoy, la nueva arranca desde su `fecha_fin` para no perder
 * días ya pagados; si ya venció, arranca hoy.
 */
export interface RenovarMembresiaFormulario {
  /** Texto, igual que el resto de importes (ver `precio.util.ts`). */
  precio_pagado: string;
  /** Omitido = se renueva con el MISMO plan. El backend rechaza los planes
   * `por_sesion`, que no generan membresía. */
  plan_id?: number;
}

/** Cuerpo de `POST /api/membresias/{id}/cancelar/`. */
export interface CancelarMembresiaFormulario {
  /** Obligatorio y no vacío: lo exigen el servicio y un CHECK de la base
   * (`ck_membresias_cancel`). Revocar el acceso de alguien es una operación
   * que queda en auditoría y hay que poder justificar. */
  motivo: string;
}

/**
 * Fila del tablero de vencimientos (`GET /api/membresias/por-vencer/`,
 * `MembresiaPorVencerSerializer`): membresías vencidas, que vencen hoy o que
 * están por vencer.
 *
 * El umbral de "por vencer" NO se decide aquí: lo aplica la vista
 * `v_membresias_estado` con el `dias_aviso_vencimiento` configurado por cada
 * gimnasio. Trae el teléfono a propósito, para que en recepción se pueda
 * llamar al cliente sin abrir su ficha.
 */
export interface MembresiaPorVencer {
  id: number;
  cliente_id: number;
  cliente_nombre: string;
  cliente_telefono: string;
  plan_id: number;
  plan_nombre: string;
  sede_id: number;
  fecha_fin: string;
  /** Negativo si ya venció. */
  dias_restantes: number;
  estado_calculado: EstadoMembresia;
}
