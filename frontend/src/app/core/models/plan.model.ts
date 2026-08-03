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
