/**
 * Informes (RF-08). Todos los importes viajan como texto, igual que el resto
 * del dinero de la aplicación.
 *
 * ## Facturado y cobrado NO son el mismo número
 *
 * Desde que existen los abonos, una venta a crédito suma a `facturado` y no
 * a `cobrado`. Los informes devuelven siempre los dos porque responden
 * preguntas distintas: "¿cuánto vendí?" y "¿cuánto entró en caja?".
 */

/** Respuesta de `GET /api/reportes/ventas/`. */
export interface ReporteVentas {
  /** Suma de `ventas.total`: lo que se vendió. */
  facturado: string;
  /** Suma de `pagos.monto`: lo que realmente entró. */
  cobrado: string;
  /**
   * `facturado − cobrado` DENTRO DEL RANGO. Puede salir negativa y no es un
   * error: un abono de hoy sobre una venta del mes pasado entra en `cobrado`
   * pero no en `facturado`.
   */
  diferencia: string;
  descuentos: string;
  numero_ventas: number;
  /** Desglose por estado de cobro: `pagada`, `parcial`, `pendiente`. */
  por_estado: Record<string, { numero: number; total: string }>;
}

/** Una fila del corte de caja: un día o un mes. */
export interface PeriodoCaja {
  /** `YYYY-MM-DD`. Con agrupación mensual, el primer día del mes. */
  periodo: string;
  ingreso_ventas: string;
  ingreso_otros: string;
  efectivo: string;
  transferencia: string;
  tarjeta: string;
  total_recibido: string;
}

/** Respuesta de `GET /api/reportes/caja/`. */
export interface ReporteCaja {
  agrupar: 'dia' | 'mes';
  periodos: PeriodoCaja[];
  totales: Omit<PeriodoCaja, 'periodo'>;
}

/** Una venta con saldo dentro de la cartera de un cliente. */
export interface VentaEnDeuda {
  venta_id: number;
  /** Número visible del recibo, único por sede. */
  consecutivo: number | null;
  fecha_hora: string;
  total: string;
  total_pagado: string;
  saldo: string;
}

/** Un cliente que debe dinero, con el detalle de sus ventas pendientes. */
export interface Deudor {
  cliente_id: number | null;
  cliente_nombre: string;
  saldo_total: string;
  ventas: VentaEnDeuda[];
}

/**
 * Respuesta de `GET /api/reportes/cartera/`.
 *
 * NO admite rango de fechas a propósito: una deuda no pertenece a un mes,
 * sigue viva hasta que se cobre. Acotarla por fechas daría menos de lo que
 * realmente se debe.
 */
export interface ReporteCartera {
  deudores: Deudor[];
  totales: { saldo: string; clientes: number; ventas: number };
}

/** Utilidad de un producto en el periodo consultado. */
export interface UtilidadProducto {
  producto_id: number;
  producto_nombre: string;
  unidades: string;
  ingresos: string;
  /** Costo COPIADO en la línea al vender, no el del catálogo de hoy. Por eso
   * un error de costo ya vendido no se corrige cambiando el producto. */
  costo: string;
  utilidad: string;
  /** Texto con un decimal, o `'—'` si no hubo ventas sobre las que calcular. */
  margen_pct: string;
}

/**
 * Respuesta de `GET /api/reportes/utilidad/`. Exige `costos.ver`.
 *
 * Productos y planes van SEPARADOS a propósito: solo los productos tienen
 * costo de adquisición. Lo que cuesta prestar un plan son el alquiler, el
 * personal y los servicios —los `gastos` de RF-24—, así que sumar los
 * ingresos de planes como si fueran ganancia daría una cifra falsa.
 */
export interface ReporteUtilidad {
  productos: { ingresos: string; costo: string; utilidad: string; margen_pct: string };
  planes: { ingresos: string };
  /**
   * Cuánto de lo vendido EN EL PERIODO sigue sin cobrar.
   *
   * El informe cuenta al vender, no al cobrar: el producto ya salió del
   * inventario, así que el costo ya se cargó y el ingreso tiene que medirse
   * en el mismo instante. Este número existe para que la utilidad no se
   * confunda con dinero disponible.
   */
  pendiente_de_cobro: string;
  gastos: { total: string; registrados: number };
  /**
   * Utilidad de productos + ingresos por planes − gastos. Lo que se entiende
   * por "la ganancia".
   *
   * ADVERTENCIA: las tres partes no comparten base temporal. La utilidad de
   * productos se cuenta al VENDER (el producto ya salió del inventario) y los
   * gastos al PAGARLOS. Un mes con mucha venta a crédito y el arriendo pagado
   * sale peor de lo que fue, y el siguiente mejor. Es correcto y es la
   * práctica habitual, pero la pantalla tiene que decirlo.
   */
  utilidad_neta: string;
  detalle: UtilidadProducto[];
}

/** Una fila del informe por producto. */
export interface ProductoVendido {
  producto_id: number;
  producto_nombre: string;
  unidades: string;
  /**
   * BRUTO, antes del descuento de la venta: la línea guarda
   * `cantidad × precio_unitario` y el descuento vive en la cabecera. El
   * descuento total va aparte, en el informe de ventas.
   */
  importe: string;
  /** Existencias de HOY en la sede consultada, no del final del rango. */
  stock_actual: string;
}

/** Respuesta de `GET /api/reportes/productos/`. */
export interface ReporteProductos {
  productos: ProductoVendido[];
  totales: { unidades: string; importe: string; productos_distintos: number };
}
