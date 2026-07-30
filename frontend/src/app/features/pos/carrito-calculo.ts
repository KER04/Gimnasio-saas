import { LineaCarrito } from './carrito.model';

/**
 * Lógica pura de cálculo del carrito del POS (Parte B del encargo).
 *
 * Deliberadamente sin ningún import de Angular/RxJS/HTTP: son funciones
 * puras (mismos argumentos -> mismo resultado, sin efectos secundarios) para
 * que las pruebas unitarias (`carrito-calculo.spec.ts`) corran bajo
 * cualquier test runner sin necesitar Chrome/Karma (ver Verificación §2 del
 * encargo: Karma no se puede ejecutar en este entorno).
 *
 * Los montos se redondean a 2 decimales por seguridad de punto flotante,
 * aunque el backend trabaja en pesos enteros (COP no usa decimales) y los
 * envía como string `Decimal`.
 */

function redondear(valor: number): number {
  return Math.round((valor + Number.EPSILON) * 100) / 100;
}

/** Suma de `cantidad * precioUnitario` de todas las líneas. */
export function calcularSubtotal(lineas: readonly LineaCarrito[]): number {
  const subtotal = lineas.reduce((acc, linea) => acc + linea.cantidad * linea.precioUnitario, 0);
  return redondear(subtotal);
}

/** Total = subtotal - descuento, nunca negativo. */
export function calcularTotal(subtotal: number, descuento: number): number {
  const total = subtotal - descuento;
  return redondear(Math.max(total, 0));
}

/** Dinero que falta por recibir (0 si el monto recibido ya cubre o supera el total). */
export function calcularSaldoPendiente(total: number, montoRecibido: number): number {
  return redondear(Math.max(total - montoRecibido, 0));
}

/** Vueltas a entregar (0 si el monto recibido no alcanza a cubrir el total). */
export function calcularCambio(total: number, montoRecibido: number): number {
  return redondear(Math.max(montoRecibido - total, 0));
}

/** Una venta con saldo pendiente (pago parcial) exige cliente identificado
 * (el backend rechaza con VentaError si no se cumple, ver
 * `apps/ventas/services.py::registrar_venta`); esto la anticipa en el
 * cliente como una validación clara antes de llamar al API. */
export function requiereClientePorPago(total: number, montoRecibido: number): boolean {
  return montoRecibido < total;
}

/** Todo descuento mayor que cero exige motivo (mismo criterio que el backend). */
export function requiereMotivoDescuento(descuento: number): boolean {
  return descuento > 0;
}

/** Cantidad de unidades que aún se pueden añadir de un producto sin superar su stock. */
export function unidadesDisponibles(
  stockDisponible: number | null,
  cantidadYaEnCarrito: number,
): number {
  if (stockDisponible === null) {
    return Infinity;
  }
  return Math.max(stockDisponible - cantidadYaEnCarrito, 0);
}
