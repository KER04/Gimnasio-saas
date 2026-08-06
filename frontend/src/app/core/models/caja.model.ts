/**
 * Movimientos de caja SIN venta detrás (RF-24 y RF-07).
 *
 * Un gasto no tiene estado "anulado" —la tabla no tiene esa columna—, así que
 * corregir un error es editar o borrar de verdad. Cada cambio queda en la
 * auditoría del gimnasio con quién, cuándo y qué había antes.
 */

export interface CategoriaGasto {
  id: number;
  nombre: string;
  activa: boolean;
}

export interface CategoriaIngreso {
  id: number;
  nombre: string;
  subcategoria: string | null;
  es_sistema: boolean;
  activa: boolean;
}

export interface Gasto {
  id: number;
  categoria_gasto: number;
  categoria_nombre: string;
  monto: string;
  fecha: string;
  descripcion: string;
  comprobante_url: string | null;
  es_recurrente: boolean;
  sede: number;
  sede_nombre: string;
  usuario: number;
  usuario_nombre: string;
  creado_en: string;
}

export interface GastoFormulario {
  categoria_gasto: number;
  sede: number;
  monto: string;
  fecha?: string;
  descripcion: string;
  es_recurrente?: boolean;
}

export type FormaPago = 'efectivo' | 'transferencia' | 'tarjeta';

export interface IngresoOtro {
  id: number;
  categoria_ingreso: number;
  categoria_nombre: string;
  monto: string;
  forma_pago: FormaPago;
  descripcion: string;
  fecha: string;
  sede: number;
  sede_nombre: string;
  usuario: number;
  usuario_nombre: string;
  creado_en: string;
}

export interface IngresoFormulario {
  categoria_ingreso: number;
  sede: number;
  monto: string;
  forma_pago: FormaPago;
  fecha?: string;
  descripcion: string;
}

export const ETIQUETAS_FORMA_PAGO: Record<FormaPago, string> = {
  efectivo: 'Efectivo',
  transferencia: 'Transferencia',
  tarjeta: 'Tarjeta',
};
