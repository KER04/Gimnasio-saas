/**
 * Contrato de `apps/ventas/serializers.py` y `views.py` (leído del backend,
 * no inventado). Todos los montos son `string` porque el backend serializa
 * `Decimal` a texto por defecto en DRF.
 */

export type FormaPago = 'efectivo' | 'transferencia' | 'tarjeta';
export type EstadoVenta = 'pagada' | 'parcial' | 'pendiente' | 'anulada';
export type TipoItemVenta = 'producto' | 'plan';

export interface ItemVentaInput {
  tipo_item: TipoItemVenta;
  producto_id?: number;
  plan_id?: number;
  cantidad: string | number;
  entrenador_id?: number | null;
  descripcion?: string;
}

/** Cuerpo de `POST /api/ventas/` (`VentaCreateSerializer`). */
export interface VentaCreateRequest {
  sede_id: number;
  cliente_id?: number | null;
  items: ItemVentaInput[];
  descuento?: string | number;
  motivo_descuento?: string | null;
  forma_pago?: FormaPago | null;
  monto_pago_inicial?: string | number;
  fecha_inicio_membresia?: string;
}

export interface DetalleVenta {
  id: number;
  tipo_item: TipoItemVenta;
  producto: number | null;
  plan: number | null;
  categoria_ingreso: number;
  descripcion: string;
  cantidad: string;
  precio_unitario: string;
  /** Ausente si el usuario no tiene `costos.ver` (ver `Producto.costo`). */
  costo_unitario?: string;
  total_linea: string;
}

export interface Pago {
  id: number;
  usuario: number;
  monto: string;
  forma_pago: FormaPago;
  es_pago_inicial: boolean;
  fecha_hora: string;
  anulado: boolean;
}

/** Respuesta de `POST /api/ventas/`, `GET /api/ventas/{id}/` y elementos de `GET /api/ventas/`. */
export interface Venta {
  id: number;
  sede: number;
  cliente: number | null;
  usuario: number;
  consecutivo: number;
  fecha_hora: string;
  subtotal: string;
  descuento: string;
  motivo_descuento: string | null;
  total: string;
  estado: EstadoVenta;
  anulada_por: number | null;
  motivo_anulacion: string | null;
  anulada_en: string | null;
  detalles: DetalleVenta[];
  pagos: Pago[];
  saldo: string;
}

export interface AnularVentaRequest {
  motivo: string;
}

export interface AbonoRequest {
  monto: string | number;
  forma_pago: FormaPago;
}

/** Forma habitual de un error 400 de DRF: `{detail: string}` o
 * `{campo: string[]}`. El frontend intenta ambas para mostrar el mensaje
 * del backend tal cual, en español. */
export interface ErrorApi {
  detail?: string;
  [campo: string]: unknown;
}
