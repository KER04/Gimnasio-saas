/**
 * Inventario: productos, categorías y kardex.
 *
 * Los importes y cantidades viajan como texto, igual que en `plan.model.ts`:
 * se formatean al mostrarlos y nunca se opera con ellos como `number`.
 */

/** Producto del catálogo (`GET /api/productos/`, `ProductoSerializer`). */
export interface Producto {
  id: number;
  nombre: string;
  marca: string | null;
  presentacion: string | null;
  codigo_barras: string | null;
  categoria_producto: number | null;
  categoria_nombre: string | null;
  precio_venta: string;
  /**
   * OPCIONAL a propósito: el backend BORRA este campo de la respuesta a
   * quien no tenga el permiso `costos.ver`, así que puede no venir. No es un
   * margen que se pueda dar por hecho.
   */
  costo?: string;
  stock_minimo: string | null;
  activo: boolean;
  /**
   * Existencias en la sede consultada. `null` cuando la petición no indicó
   * `sede_id`: no significa "sin stock", significa "no se preguntó por
   * ninguna sede".
   */
  stock: string | null;
}

/**
 * Cuerpo de `POST`/`PATCH /api/productos/`.
 *
 * NO incluye `stock` a propósito: las existencias no se editan a mano, se
 * mueven registrando un movimiento de kardex. Escribirlas directamente
 * desincronizaría el libro de movimientos.
 */
export interface ProductoFormulario {
  nombre: string;
  categoria_producto: number;
  precio_venta: string;
  marca?: string | null;
  presentacion?: string | null;
  codigo_barras?: string | null;
  costo?: string;
  stock_minimo?: string;
  activo?: boolean;
}

/** Categoría de producto (`/api/categorias-producto/`). */
export interface CategoriaProducto {
  id: number;
  nombre: string;
  activa: boolean;
}

export interface CategoriaFormulario {
  nombre: string;
  activa?: boolean;
}

/** Tipos del kardex. Los dos últimos los genera la venta, no esta API. */
export type TipoMovimiento =
  | 'entrada_compra'
  | 'ajuste_manual'
  | 'salida_venta'
  | 'reverso_anulacion';

export const ETIQUETAS_TIPO_MOVIMIENTO: Record<TipoMovimiento, string> = {
  entrada_compra: 'Entrada por compra',
  ajuste_manual: 'Ajuste manual',
  salida_venta: 'Salida por venta',
  reverso_anulacion: 'Reverso por anulación',
};

/** Fila del kardex (`GET /api/movimientos-inventario/`). */
export interface MovimientoInventario {
  id: number;
  producto: number;
  producto_nombre: string | null;
  sede: number;
  sede_nombre: string | null;
  usuario: number;
  usuario_nombre: string | null;
  tipo: TipoMovimiento;
  /** CON SIGNO: positiva entra, negativa sale. */
  cantidad: string;
  /** Existencias tras el movimiento. Lo calcula el disparador de la base. */
  saldo_resultante: string;
  costo_unitario?: string | null;
  motivo: string | null;
  venta: number | null;
  fecha_hora: string;
}

/**
 * Cuerpo de `POST /api/movimientos-inventario/`.
 *
 * Solo se admiten `entrada_compra` y `ajuste_manual`: las salidas por venta
 * y los reversos los emite la propia venta, y permitirlos aquí dejaría
 * fabricar movimientos de venta sin venta detrás.
 */
export interface MovimientoFormulario {
  producto_id: number;
  sede_id: number;
  tipo: 'entrada_compra' | 'ajuste_manual';
  /** Con signo. La entrada exige positiva; el ajuste admite ambos signos. */
  cantidad: string;
  costo_unitario?: string;
  /** Obligatorio en los ajustes: un ajuste sin motivo es inauditable. */
  motivo?: string;
}
