/**
 * Contrato de la capa de planes (`GET /api/planes/`, `apps.ventas.serializers.PlanSerializer`).
 * `precio` viaja como texto (`"50000.00"`), igual que el resto de importes
 * del backend: se formatea solo al mostrarlo, nunca se opera con él como
 * `number` (ver el mismo criterio documentado en `cliente.model.ts`).
 */

/** Tipo de plan (`Plan.TipoPlan` en el backend). */
export type TipoPlan = 'mensual' | 'quincenal' | 'por_sesion';

/** Un plan del catálogo, tal como lo devuelve `GET /api/planes/` (paginado). */
export interface Plan {
  id: number;
  nombre: string;
  tipo: TipoPlan;
  duracion_dias: number | null;
  precio: string;
  requiere_entrenador: boolean;
  sede: number | null;
  activo: boolean;
}

/** Payload de escritura de un plan (`POST`/`PATCH /api/planes/`). */
export interface PlanFormulario {
  nombre: string;
  tipo: TipoPlan;
  /** `null` obligatorio cuando `tipo` es `'por_sesion'` (ck_planes_duracion). */
  duracion_dias: number | null;
  /** Texto, igual que en `Plan.precio`: nunca se opera como `number`. */
  precio: string;
  requiere_entrenador: boolean;
  /** `null` = plan disponible en todas las sedes del gimnasio. */
  sede: number | null;
  activo: boolean;
}
