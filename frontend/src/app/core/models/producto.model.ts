/**
 * Catálogo de productos vendibles (buscador del POS).
 *
 * `costo` puede no llegar en absoluto si el usuario autenticado no tiene el
 * permiso `costos.ver` (ver `apps/ventas/serializers.py::_ocultar_campos_de_costo`
 * en el backend, que lo elimina del diccionario de salida en vez de mandarlo
 * en `null`). Por eso es opcional aquí y el frontend nunca debe asumir que
 * existe.
 *
 * `stock` viene como string (el backend serializa `Decimal` a texto) y es
 * `null` si la petición no incluyó `sede_id`.
 */
export interface Producto {
  id: number;
  nombre: string;
  marca: string | null;
  presentacion: string | null;
  codigo_barras: string | null;
  categoria_producto: number;
  precio_venta: string;
  costo?: string;
  stock_minimo: string;
  activo: boolean;
  stock: string | null;
}
