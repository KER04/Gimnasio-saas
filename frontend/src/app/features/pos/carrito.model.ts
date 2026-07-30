/** Una línea del carrito del POS: producto o plan, ya resuelto a datos concretos. */
export interface LineaCarrito {
  /** Id local de la línea (no del backend), para poder identificarla en la plantilla. */
  idLocal: string;
  tipoItem: 'producto' | 'plan';
  productoId?: number;
  planId?: number;
  descripcion: string;
  cantidad: number;
  precioUnitario: number;
  /** Solo para productos: tope de unidades vendibles (stock de la sede). `null` = sin límite conocido. */
  stockDisponible: number | null;
}
