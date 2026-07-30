import {
  calcularCambio,
  calcularSaldoPendiente,
  calcularSubtotal,
  calcularTotal,
  requiereClientePorPago,
  requiereMotivoDescuento,
  unidadesDisponibles,
} from './carrito-calculo';
import { LineaCarrito } from './carrito.model';

/**
 * Pruebas de la lógica PURA de cálculo del carrito (Parte B / Verificación
 * §2 del encargo). Karma necesita Chrome, que no está instalado en este
 * WSL, así que estas pruebas NO se pudieron ejecutar en este entorno (ver
 * reporte) — quedan listas para correr en CI con `ng test` en cuanto haya
 * un navegador disponible.
 */

function linea(parciales: Partial<LineaCarrito>): LineaCarrito {
  return {
    idLocal: 'x',
    tipoItem: 'producto',
    descripcion: 'Producto de prueba',
    cantidad: 1,
    precioUnitario: 0,
    stockDisponible: null,
    ...parciales,
  };
}

describe('calcularSubtotal', () => {
  it('devuelve 0 con el carrito vacío', () => {
    expect(calcularSubtotal([])).toBe(0);
  });

  it('suma cantidad * precioUnitario de todas las líneas', () => {
    const lineas = [
      linea({ cantidad: 2, precioUnitario: 15000 }),
      linea({ cantidad: 1, precioUnitario: 50000 }),
    ];
    expect(calcularSubtotal(lineas)).toBe(80000);
  });

  it('redondea a 2 decimales ante imprecisión de punto flotante', () => {
    const lineas = [linea({ cantidad: 3, precioUnitario: 0.1 })];
    expect(calcularSubtotal(lineas)).toBe(0.3);
  });
});

describe('calcularTotal', () => {
  it('resta el descuento del subtotal', () => {
    expect(calcularTotal(100000, 20000)).toBe(80000);
  });

  it('nunca es negativo aunque el descuento supere el subtotal', () => {
    expect(calcularTotal(10000, 50000)).toBe(0);
  });
});

describe('calcularSaldoPendiente', () => {
  it('es 0 cuando el pago cubre el total exacto', () => {
    expect(calcularSaldoPendiente(50000, 50000)).toBe(0);
  });

  it('es 0 cuando el pago supera el total (no queda "saldo negativo")', () => {
    expect(calcularSaldoPendiente(50000, 60000)).toBe(0);
  });

  it('calcula lo que falta cuando el pago es parcial', () => {
    expect(calcularSaldoPendiente(50000, 20000)).toBe(30000);
  });
});

describe('calcularCambio', () => {
  it('es 0 cuando el pago no alcanza a cubrir el total', () => {
    expect(calcularCambio(50000, 20000)).toBe(0);
  });

  it('calcula la vuelta cuando el pago supera el total', () => {
    expect(calcularCambio(50000, 60000)).toBe(10000);
  });

  it('es 0 con pago exacto', () => {
    expect(calcularCambio(50000, 50000)).toBe(0);
  });
});

describe('requiereClientePorPago', () => {
  it('exige cliente si el pago recibido es menor que el total', () => {
    expect(requiereClientePorPago(50000, 20000)).toBe(true);
  });

  it('no exige cliente con pago exacto', () => {
    expect(requiereClientePorPago(50000, 50000)).toBe(false);
  });

  it('no exige cliente con pago mayor (vuelta)', () => {
    expect(requiereClientePorPago(50000, 60000)).toBe(false);
  });
});

describe('requiereMotivoDescuento', () => {
  it('no exige motivo con descuento en cero', () => {
    expect(requiereMotivoDescuento(0)).toBe(false);
  });

  it('exige motivo con cualquier descuento mayor que cero', () => {
    expect(requiereMotivoDescuento(1)).toBe(true);
  });
});

describe('unidadesDisponibles', () => {
  it('es Infinity cuando no se conoce el stock (sede no indicada)', () => {
    expect(unidadesDisponibles(null, 3)).toBe(Infinity);
  });

  it('descuenta lo ya puesto en el carrito', () => {
    expect(unidadesDisponibles(10, 4)).toBe(6);
  });

  it('nunca es negativa', () => {
    expect(unidadesDisponibles(5, 9)).toBe(0);
  });
});
