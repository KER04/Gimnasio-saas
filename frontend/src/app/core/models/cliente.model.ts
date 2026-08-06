/**
 * Contrato de la capa de clientes con el backend (`apps.clientes`, RF-03,
 * RF-09, RF-16). Tipos planos, sin lógica.
 *
 * Los campos `DecimalField` de DRF viajan como texto (p. ej. `"45000.00"`),
 * nunca como `number`: así no se pierde precisión y coincide exactamente
 * con lo que el backend serializa. Se formatean solo al mostrarlos.
 */

/** Sexo del cliente (Parte C, opcional). */
export type Sexo = 'M' | 'F' | 'O';

/** Ficha completa de un cliente (`GET/POST/PATCH /api/clientes/{id}/`). */
export interface Cliente {
  id: number;
  nombre: string;
  cedula: string;
  telefono: string;
  direccion: string;
  sexo: Sexo | null;
  sede_origen: number;
  fecha_registro: string;
  activo: boolean;
  eliminado_en: string | null;
  creado_en: string;
  actualizado_en: string;
  /** `null` = nunca se registró la decisión (distinto de `false`, que es negarla). */
  autorizacion_tratamiento_datos: boolean | null;
  autorizacion_biometria: boolean | null;
}

/** Estados calculados de `v_membresias_estado` (RF-16). */
export type EstadoMembresia = 'activa' | 'por_vencer' | 'vence_hoy' | 'vencida' | 'cancelada';

/** Valores válidos del filtro `?estado=` del listado (`GET /api/clientes/`).
 * `sin_membresia` no es un estado de `v_membresias_estado`: significa que el
 * cliente no tiene ninguna membresía vigente (`membresia_vigente === null`). */
export type EstadoFiltroCliente = 'activa' | 'por_vencer' | 'vence_hoy' | 'vencida' | 'sin_membresia';

/** Membresía vigente resumida, tal como llega embebida en cada fila del
 * listado (anotación del queryset, no una consulta aparte). `null` si el
 * cliente no tiene ninguna membresía activa. */
export interface MembresiaVigenteResumen {
  plan_nombre: string;
  estado_calculado: EstadoMembresia;
  fecha_fin: string;
  dias_restantes: number;
}

/**
 * Filtro `?eliminados=` del listado: un filtro más, al lado de `estado` y
 * `plan`. Los clientes eliminados no viven en una pantalla aparte, se ven en
 * la misma lista acotando desde aquí.
 */
export type FiltroEliminados = 'excluir' | 'incluir' | 'solo';

/** Opciones del selector, en el orden en que se ofrecen. */
export const OPCIONES_ELIMINADOS: { valor: FiltroEliminados; etiqueta: string }[] = [
  { valor: 'excluir', etiqueta: 'Solo activos' },
  { valor: 'incluir', etiqueta: 'Activos y eliminados' },
  { valor: 'solo', etiqueta: 'Solo eliminados' },
];

/** Fila mínima del listado (`ClienteResumenSerializer`, `GET /api/clientes/`). */
export interface ClienteResumen {
  id: number;
  nombre: string;
  cedula: string;
  telefono: string;
  activo: boolean;
  membresia_vigente: MembresiaVigenteResumen | null;
  ultima_visita: string | null;
  /** Fecha del borrado lógico, o `null` si el cliente está vivo. Solo llega
   * distinto de `null` pidiendo la papelera (`incluir_eliminados`), porque el
   * listado normal no devuelve eliminados. */
  eliminado_en: string | null;
}

/** Cuerpo de alta/edición (`POST`/`PATCH /api/clientes/`). Las autorizaciones
 * solo se registran en la creación: `update()` las ignora si llegan. */
export interface ClienteFormulario {
  nombre: string;
  cedula: string;
  telefono: string;
  direccion: string;
  sexo?: Sexo | null;
  sede_origen?: number | null;
  autoriza_tratamiento_datos?: boolean | null;
  autoriza_biometria?: boolean | null;
}

/** Una membresía con su estado YA calculado por la base de datos
 * (`GET /api/clientes/{id}/membresias/`). Un cliente puede tener varias
 * membresías activas a la vez. */
export interface MembresiaResumen {
  id: number;
  plan_id: number;
  sede_id: number;
  fecha_inicio: string;
  fecha_fin: string;
  dias_restantes: number;
  estado_calculado: EstadoMembresia;
}

/** Un abono (pago) sobre una venta, tal como viaja en la cartera y en el
 * historial de compras. */
export interface AbonoVenta {
  id: number;
  monto: string;
  forma_pago: string;
  es_pago_inicial: boolean;
  fecha_hora: string;
  usuario: number;
  /** Solo presente en el historial de compras (`VentaSerializer.pagos`), no en la deuda. */
  anulado?: boolean;
}

/** Una línea (concepto) de una venta. `costo_unitario` solo viaja si el
 * usuario tiene `costos.ver`: por eso es opcional. */
export interface DetalleVentaCliente {
  id: number;
  tipo_item: string;
  producto?: number | null;
  plan?: number | null;
  categoria_ingreso?: string | null;
  descripcion: string;
  cantidad: string;
  precio_unitario: string;
  costo_unitario?: string;
  total_linea: string;
}

/** Una venta con saldo pendiente, con sus líneas y sus abonos en orden
 * cronológico (RF-09, pestaña "Deuda" de la ficha). */
export interface VentaConSaldo {
  /** Identificador interno. NO se enseña: para el usuario, la venta es su
   * `consecutivo`, que es el número del recibo. */
  venta_id: number;
  /** Número visible de la venta, único por sede. */
  consecutivo: number | null;
  fecha_hora: string;
  total: string;
  total_pagado: string;
  saldo: string;
  detalles: DetalleVentaCliente[];
  abonos: AbonoVenta[];
}

/** Cuerpo de `GET /api/clientes/{id}/deuda/`. */
export interface DeudaCliente {
  total_adeudado: string;
  ventas: VentaConSaldo[];
}

/** Una venta del historial de compras (`GET /api/clientes/{id}/compras/`,
 * paginado). Incluye también las anuladas, marcadas con `estado='anulada'`. */
export interface CompraCliente {
  id: number;
  sede: number;
  cliente: number;
  usuario: number;
  consecutivo: string;
  fecha_hora: string;
  subtotal: string;
  descuento: string;
  motivo_descuento: string | null;
  total: string;
  estado: string;
  anulada_por: number | null;
  motivo_anulacion: string | null;
  anulada_en: string | null;
  detalles: DetalleVentaCliente[];
  pagos: AbonoVenta[];
  saldo: string;
}

/** Una asistencia del historial de ingresos (`GET /api/clientes/{id}/asistencias/`,
 * paginado, más reciente primero). */
export interface AsistenciaCliente {
  id: number;
  sede: number;
  cliente: number;
  cliente_nombre: string | null;
  cliente_cedula: string | null;
  venta: number | null;
  metodo: string;
  fecha_hora: string;
  con_membresia_vigente: boolean;
  autorizado_por: number | null;
  autorizado_por_nombre: string | null;
  motivo_autorizacion: string | null;
}
