/**
 * Contrato de ventas y abonos (RF-09).
 *
 * Una membresía se puede adquirir por dos vías distintas, y solo UNA de las
 * dos admite abonos:
 *
 * - **Vendida** (`POST /api/ventas/`): crea venta + pago + membresía. Si lo
 *   que se paga en el momento es menor que el total, la venta queda con
 *   saldo y se va cobrando con abonos.
 * - **Asignada directamente** (`POST /api/membresias/`, ver
 *   `membresia.model.ts`): no pasa por caja, `venta = NULL`. Al no haber
 *   venta no hay total ni saldo, así que NO puede tener abonos.
 */

/** Formas de pago admitidas (`Pago.FormaPago` en el backend). */
export type FormaPago = 'efectivo' | 'transferencia' | 'tarjeta';

export const ETIQUETAS_FORMA_PAGO: Record<FormaPago, string> = {
  efectivo: 'Efectivo',
  transferencia: 'Transferencia',
  tarjeta: 'Tarjeta',
};

/** Estado de cobro de una venta. Lo recalcula el backend solo, a partir de
 * los pagos: nunca se envía desde el cliente. */
export type EstadoVenta = 'pendiente' | 'parcial' | 'pagada' | 'anulada';

/** Una línea de la venta. Para membresías siempre es `tipo_item: 'plan'`. */
export interface ItemVenta {
  tipo_item: 'plan' | 'producto';
  plan_id?: number;
  producto_id?: number;
  /** Texto, como el resto de importes y cantidades. */
  cantidad: string;
}

/** Cuerpo de `POST /api/ventas/`. */
export interface VentaFormulario {
  sede_id: number;
  /**
   * OPCIONAL: una venta de mostrador pagada al contado no tiene por qué
   * identificar a nadie. Pasa a ser OBLIGATORIO en dos casos, que impone
   * `registrar_venta`: si algún ítem es un plan con vigencia (la membresía
   * tiene que ser de alguien) o si queda saldo pendiente (nadie debe dinero
   * de forma anónima).
   */
  cliente_id?: number;
  items: ItemVenta[];
  /** Importe descontado sobre el subtotal. Exige `motivo_descuento` en
   * cuanto es mayor que cero, y no puede superar el subtotal. */
  descuento?: string;
  motivo_descuento?: string;
  /** Obligatoria si `monto_pago_inicial` es mayor que cero. */
  forma_pago?: FormaPago;
  /**
   * Dinero recibido en el momento de la venta. Puede ir de 0 al total:
   * - `= total` → la venta nace `pagada`.
   * - `> 0` y menor que el total → nace `parcial`, con saldo a cobrar.
   * - `0` → nace `pendiente`.
   *
   * El backend EXIGE cliente en los dos últimos casos: nadie queda debiendo
   * de forma anónima.
   */
  monto_pago_inicial: string;
  /** `YYYY-MM-DD`. Desde cuándo cuenta la vigencia de la membresía. */
  fecha_inicio_membresia?: string;
}

/** Cuerpo de `POST /api/ventas/{id}/abonos/`. */
export interface AbonoFormulario {
  /** Mayor que cero y nunca superior al saldo pendiente (lo valida también
   * el backend, que es la autoridad). */
  monto: string;
  forma_pago: FormaPago;
}

/** Lo que devuelven crear venta y abonar. Solo se declara lo que se usa. */
export interface VentaCreada {
  id: number;
  total: string;
  estado: EstadoVenta;
}

/** Una línea de la venta, tal como la devuelve `VentaSerializer`. */
export interface DetalleVenta {
  id: number;
  tipo_item: 'producto' | 'plan';
  producto: number | null;
  plan: number | null;
  descripcion: string;
  cantidad: string;
  precio_unitario: string;
  /** Solo visible con permiso `costos.ver`; si no, el backend lo omite. */
  costo_unitario?: string;
  total_linea: string;
}

/** Un pago de la venta. `anulado` distingue los que ya no cuentan. */
export interface PagoVenta {
  id: number;
  usuario: number;
  monto: string;
  forma_pago: FormaPago;
  es_pago_inicial: boolean;
  fecha_hora: string;
  anulado: boolean;
}

/**
 * Venta completa (`GET /api/ventas/` y `GET /api/ventas/{id}/`).
 *
 * El número que se enseña es el `consecutivo` (único por sede, el del
 * recibo), NO el `id`, que es el identificador interno.
 */
export interface Venta {
  id: number;
  sede: number;
  cliente: number | null;
  /** `null` en una venta de mostrador: pagada al contado y sin identificar
   * a nadie. No es un dato que falte. */
  cliente_nombre: string | null;
  usuario: number;
  usuario_nombre: string | null;
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
  pagos: PagoVenta[];
  /** Lo que falta por cobrar: total menos pagos no anulados. */
  saldo: string;
}

/** Cuerpo de `POST /api/ventas/{id}/anular/`. */
export interface AnularVentaFormulario {
  /** Obligatorio. Anular devuelve el stock y revierte los pagos, así que
   * tiene que quedar constancia de por qué. */
  motivo: string;
}
