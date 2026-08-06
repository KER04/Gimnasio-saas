import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { ClientesService } from '../../core/services/clientes.service';
import { PlanesService } from '../../core/services/planes.service';
import { ProductosService } from '../../core/services/productos.service';
import { VentasService } from '../../core/services/ventas.service';
import { ClienteResumen } from '../../core/models/cliente.model';
import { Plan } from '../../core/models/plan.model';
import { Producto } from '../../core/models/producto.model';
import { ETIQUETAS_FORMA_PAGO, FormaPago, ItemVenta } from '../../core/models/venta.model';
import { formatearMonto, normalizarPrecio, precioParaMostrar, precioValido } from '../../core/utils/precio.util';

/**
 * Una línea del carrito. El precio se guarda como CADENA (el del catálogo en
 * el momento de añadirlo) y todas las sumas se hacen en céntimos enteros:
 * sumar dinero en coma flotante produce residuos del tipo 0.009999.
 */
interface LineaCarrito {
  tipo: 'producto' | 'plan';
  id: number;
  nombre: string;
  precioUnitario: string;
  cantidad: number;
  /** Solo para productos: existencias en la sede, para avisar al pasarse.
   * `null` = el backend no informó de stock. */
  stock: number | null;
  /** Solo para planes: los que tienen vigencia obligan a indicar cliente. */
  generaMembresia: boolean;
}

/** Céntimos de un importe en texto, para poder sumar con enteros. */
function centimos(valor: string): number {
  return Math.round(Number(valor) * 100);
}

/** Céntimos de vuelta a la cadena canónica que espera el backend. */
function aTexto(centimos: number): string {
  return (centimos / 100).toFixed(2);
}

/**
 * Punto de venta (RF-07/RF-09). Vende productos y planes en la misma venta,
 * admite descuento con motivo y cobro parcial.
 *
 * Toda la lógica de negocio vive en `apps.ventas.services.registrar_venta`:
 * stock (lo descuenta un trigger de la base), categorías de ingreso, creación
 * de la membresía cuando el plan tiene vigencia, y el estado de cobro. Aquí
 * solo se adelantan las reglas que el usuario puede corregir sin ir al
 * servidor, y el servidor las revalida todas.
 */
@Component({
  selector: 'app-pos',
  imports: [ReactiveFormsModule],
  templateUrl: './pos.html',
})
export class PuntoDeVenta {
  private readonly productosService = inject(ProductosService);
  private readonly planesService = inject(PlanesService);
  private readonly clientesService = inject(ClientesService);
  private readonly ventasService = inject(VentasService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeVerInventario = computed(() => this.authService.tienePermiso('inventario.ver'));
  protected readonly puedeDescontar = computed(() => this.authService.tienePermiso('ventas.descuento'));

  /** La sede del usuario. Sin ella no se puede vender: el stock y la venta
   * se registran contra una sede concreta. */
  protected readonly sedeId = computed(() => this.authService.sedeActual()?.id ?? null);
  protected readonly nombreSede = computed(() => this.authService.sedeActual()?.nombre ?? null);

  protected readonly formasPago = ETIQUETAS_FORMA_PAGO;
  protected readonly opcionesFormaPago = Object.keys(ETIQUETAS_FORMA_PAGO) as FormaPago[];

  // --- Catálogo ---
  protected readonly pestana = signal<'productos' | 'planes'>('productos');
  protected readonly buscarCatalogo = this.fb.nonNullable.control('');
  protected readonly productos = signal<Producto[]>([]);
  protected readonly planes = signal<Plan[]>([]);
  protected readonly cargandoCatalogo = signal(false);
  protected readonly errorCatalogo = signal<string | null>(null);

  /** Los planes se filtran en memoria: el catálogo es pequeño y ya viene
   * entero, así que pedirlo otra vez por cada tecla sería gasto inútil. */
  protected readonly planesFiltrados = computed(() => {
    const texto = this.textoBusqueda().trim().toLowerCase();
    const planes = this.planes();
    return texto === '' ? planes : planes.filter((p) => p.nombre.toLowerCase().includes(texto));
  });
  private readonly textoBusqueda = signal('');

  // --- Carrito ---
  protected readonly carrito = signal<LineaCarrito[]>([]);

  protected readonly subtotalCentimos = computed(() =>
    this.carrito().reduce((total, l) => total + centimos(l.precioUnitario) * l.cantidad, 0),
  );

  protected readonly descuentoCentimos = computed(() => {
    const texto = this.descuentoTexto();
    const normalizado = normalizarPrecio(texto ?? '');
    return normalizado === null ? 0 : centimos(normalizado);
  });

  protected readonly totalCentimos = computed(() =>
    Math.max(0, this.subtotalCentimos() - this.descuentoCentimos()),
  );

  /** El descuento no puede superar el subtotal (`ck_ventas_montos`). */
  protected readonly descuentoExcedido = computed(
    () => this.descuentoCentimos() > this.subtotalCentimos(),
  );

  protected readonly pagaCentimos = computed(() => {
    const normalizado = normalizarPrecio(this.pagaTexto() ?? '');
    return normalizado === null ? 0 : centimos(normalizado);
  });

  protected readonly saldoCentimos = computed(() =>
    Math.max(0, this.totalCentimos() - this.pagaCentimos()),
  );

  protected readonly pagoExcedido = computed(() => this.pagaCentimos() > this.totalCentimos());

  /** Hay algún plan con vigencia: el backend exige cliente para poder crear
   * la membresía a nombre de alguien. */
  protected readonly hayPlanConVigencia = computed(() =>
    this.carrito().some((l) => l.generaMembresia),
  );

  /** Queda saldo: nadie puede quedar debiendo de forma anónima. */
  protected readonly quedaSaldo = computed(() => this.saldoCentimos() > 0);

  protected readonly clienteObligatorio = computed(
    () => this.hayPlanConVigencia() || this.quedaSaldo(),
  );

  // --- Cliente ---
  protected readonly buscarCliente = this.fb.nonNullable.control('');
  protected readonly sugerenciasCliente = signal<ClienteResumen[]>([]);
  protected readonly clienteElegido = signal<ClienteResumen | null>(null);

  // --- Cobro ---
  protected readonly formCobro = this.fb.nonNullable.group({
    descuento: this.fb.nonNullable.control('', [precioValido]),
    motivo_descuento: this.fb.nonNullable.control(''),
    paga: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    forma_pago: this.fb.nonNullable.control<FormaPago | ''>('efectivo'),
  });

  // `FormControl.value` no es reactivo: un `computed` que lo leyera
  // directamente no volvería a recalcularse nunca (ver la nota larga en
  // `features/clientes/formulario/formulario.ts`, donde ese mismo fallo dejó
  // el alta creando clientes sin membresía en silencio). `toSignal` además
  // cancela la suscripción al destruir el componente.
  private readonly descuentoTexto = toSignal(this.formCobro.controls.descuento.valueChanges, {
    initialValue: this.formCobro.controls.descuento.value,
  });
  private readonly pagaTexto = toSignal(this.formCobro.controls.paga.valueChanges, {
    initialValue: this.formCobro.controls.paga.value,
  });

  protected readonly cobrando = signal(false);
  protected readonly errorCobro = signal<string | null>(null);
  protected readonly ventaHecha = signal<{ id: number; total: string; estado: string } | null>(null);

  constructor() {
    this.buscarCatalogo.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((texto) => {
        this.textoBusqueda.set(texto);
        this.cargarProductos();
      });

    this.buscarCliente.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((texto) => this.buscarClientes(texto));

    // El total cambia al tocar el carrito o el descuento; se propone cobrar
    // el total entero, que es el caso corriente. Rebajarlo es lo que crea el
    // saldo pendiente.
    this.planesService.listar().subscribe({
      next: (planes) => this.planes.set(planes),
      error: () => this.planes.set([]),
    });
    this.cargarProductos();
  }

  // -----------------------------------------------------------------------
  // Catálogo
  // -----------------------------------------------------------------------

  private cargarProductos(): void {
    const sede = this.sedeId();
    if (sede === null || !this.puedeVerInventario()) {
      return;
    }
    this.cargandoCatalogo.set(true);
    this.errorCatalogo.set(null);
    this.productosService.listar(sede, this.buscarCatalogo.value.trim() || undefined).subscribe({
      next: (productos) => {
        this.productos.set(productos);
        this.cargandoCatalogo.set(false);
      },
      error: () => {
        this.productos.set([]);
        this.cargandoCatalogo.set(false);
        this.errorCatalogo.set('No se pudo cargar el catálogo de productos.');
      },
    });
  }

  protected stockDe(producto: Producto): number | null {
    return producto.stock === null ? null : Number(producto.stock);
  }

  /**
   * Etiqueta de existencias, o `null` si el backend no informó de stock.
   *
   * Devuelve TEXTO y no el número a propósito: en la plantilla, un
   * `@if (stock; as n)` con stock 0 no entraría —cero es falsy— y el
   * producto agotado, que es justo el que hay que señalar, se quedaría sin
   * aviso. Una cadena no vacía siempre entra.
   */
  protected textoStock(producto: Producto): string | null {
    const stock = this.stockDe(producto);
    if (stock === null) {
      return null;
    }
    return stock > 0 ? `${stock} en existencia` : 'Sin existencias';
  }

  protected sinExistencias(producto: Producto): boolean {
    const stock = this.stockDe(producto);
    return stock !== null && stock <= 0;
  }

  protected agregarProducto(producto: Producto): void {
    this.agregarLinea({
      tipo: 'producto',
      id: producto.id,
      nombre: producto.nombre,
      precioUnitario: producto.precio_venta,
      cantidad: 1,
      stock: this.stockDe(producto),
      generaMembresia: false,
    });
  }

  protected agregarPlan(plan: Plan): void {
    this.agregarLinea({
      tipo: 'plan',
      id: plan.id,
      nombre: plan.nombre,
      precioUnitario: plan.precio,
      cantidad: 1,
      stock: null,
      generaMembresia: plan.tipo !== 'por_sesion',
    });
  }

  private agregarLinea(nueva: LineaCarrito): void {
    this.carrito.update((lineas) => {
      const existente = lineas.find((l) => l.tipo === nueva.tipo && l.id === nueva.id);
      if (existente) {
        return lineas.map((l) => (l === existente ? { ...l, cantidad: l.cantidad + 1 } : l));
      }
      return [...lineas, nueva];
    });
    this.proponerPagoTotal();
  }

  // -----------------------------------------------------------------------
  // Carrito
  // -----------------------------------------------------------------------

  protected cambiarCantidad(linea: LineaCarrito, delta: number): void {
    this.carrito.update((lineas) =>
      lineas
        .map((l) => (l === linea ? { ...l, cantidad: l.cantidad + delta } : l))
        .filter((l) => l.cantidad > 0),
    );
    this.proponerPagoTotal();
  }

  protected quitar(linea: LineaCarrito): void {
    this.carrito.update((lineas) => lineas.filter((l) => l !== linea));
    this.proponerPagoTotal();
  }

  protected vaciar(): void {
    this.carrito.set([]);
    this.clienteElegido.set(null);
    this.buscarCliente.setValue('', { emitEvent: false });
    this.sugerenciasCliente.set([]);
    this.formCobro.reset({ descuento: '', motivo_descuento: '', paga: '', forma_pago: 'efectivo' });
    this.errorCobro.set(null);
  }

  /** Rehace la propuesta de cobro con el total actual. No pisa un importe
   * que el usuario haya escrito a mano si ya no cuadra: siempre propone el
   * total, y él decide rebajarlo. */
  protected proponerPagoTotal(): void {
    this.formCobro.controls.paga.setValue(aTexto(this.totalCentimos()).replace('.00', ''));
  }

  /** `true` si alguna línea pide más unidades de las que hay en la sede. El
   * backend lo rechaza igual (lo impide un trigger), pero avisar antes evita
   * el viaje de ida y vuelta. */
  protected readonly stockInsuficiente = computed(() =>
    this.carrito().some((l) => l.stock !== null && l.cantidad > l.stock),
  );

  // -----------------------------------------------------------------------
  // Cliente
  // -----------------------------------------------------------------------

  private buscarClientes(texto: string): void {
    const limpio = texto.trim();
    if (limpio.length < 2) {
      this.sugerenciasCliente.set([]);
      return;
    }
    this.clientesService.listar(limpio).subscribe({
      next: (respuesta) => this.sugerenciasCliente.set(respuesta.results.slice(0, 6)),
      error: () => this.sugerenciasCliente.set([]),
    });
  }

  protected elegirCliente(cliente: ClienteResumen): void {
    this.clienteElegido.set(cliente);
    this.sugerenciasCliente.set([]);
    this.buscarCliente.setValue('', { emitEvent: false });
  }

  protected quitarCliente(): void {
    this.clienteElegido.set(null);
  }

  // -----------------------------------------------------------------------
  // Cobro
  // -----------------------------------------------------------------------

  protected dinero(centimosValor: number): string {
    return precioParaMostrar(aTexto(centimosValor));
  }

  protected dineroTexto(valor: string): string {
    return precioParaMostrar(valor);
  }

  protected totalLinea(linea: LineaCarrito): string {
    return this.dinero(centimos(linea.precioUnitario) * linea.cantidad);
  }

  /** Motivo obligatorio en cuanto hay descuento (lo exige `registrar_venta`). */
  protected readonly faltaMotivoDescuento = computed(
    () => this.descuentoCentimos() > 0 && this.formCobro.controls.motivo_descuento.value.trim() === '',
  );

  protected readonly puedeCobrar = computed(() => {
    if (this.carrito().length === 0 || this.cobrando()) {
      return false;
    }
    if (this.sedeId() === null) {
      return false;
    }
    if (this.descuentoExcedido() || this.pagoExcedido() || this.faltaMotivoDescuento()) {
      return false;
    }
    if (this.clienteObligatorio() && this.clienteElegido() === null) {
      return false;
    }
    // Si entra dinero hace falta decir por qué vía.
    if (this.pagaCentimos() > 0 && this.formCobro.controls.forma_pago.value === '') {
      return false;
    }
    return true;
  });

  protected cobrar(): void {
    const sede = this.sedeId();
    if (!this.puedeCobrar() || sede === null) {
      return;
    }

    const valores = this.formCobro.getRawValue();
    const items: ItemVenta[] = this.carrito().map((l) =>
      l.tipo === 'producto'
        ? { tipo_item: 'producto', producto_id: l.id, cantidad: String(l.cantidad) }
        : { tipo_item: 'plan', plan_id: l.id, cantidad: String(l.cantidad) },
    );

    const pagaAlgo = this.pagaCentimos() > 0;
    const hayDescuento = this.descuentoCentimos() > 0;
    const cliente = this.clienteElegido();

    this.cobrando.set(true);
    this.errorCobro.set(null);

    this.ventasService
      .registrar({
        sede_id: sede,
        // El cliente es opcional cuando se venden solo productos y se paga
        // todo: una venta de mostrador no tiene por qué identificar a nadie.
        ...(cliente ? { cliente_id: cliente.id } : {}),
        items,
        ...(hayDescuento
          ? {
              descuento: aTexto(this.descuentoCentimos()),
              motivo_descuento: valores.motivo_descuento.trim(),
            }
          : {}),
        ...(pagaAlgo ? { forma_pago: valores.forma_pago as FormaPago } : {}),
        monto_pago_inicial: aTexto(this.pagaCentimos()),
      })
      .subscribe({
        next: (venta) => {
          this.cobrando.set(false);
          this.ventaHecha.set({ id: venta.id, total: venta.total, estado: venta.estado });
          this.vaciar();
          // El stock cambió: se recarga para que la siguiente venta parta de
          // existencias reales.
          this.cargarProductos();
        },
        error: (error: unknown) => {
          this.cobrando.set(false);
          this.errorCobro.set(this.mensajeDeError(error));
        },
      });
  }

  protected irALaVenta(): void {
    const cliente = this.clienteElegido();
    if (cliente) {
      this.router.navigate(['/clientes', cliente.id]);
    }
  }

  protected cerrarAviso(): void {
    this.ventaHecha.set(null);
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse && error.error) {
      const cuerpo = error.error as Record<string, unknown>;
      if (typeof cuerpo['detail'] === 'string') {
        return cuerpo['detail'];
      }
      const primero = Object.values(cuerpo)[0];
      if (typeof primero === 'string') {
        return primero;
      }
      if (Array.isArray(primero) && typeof primero[0] === 'string') {
        return primero[0];
      }
    }
    return 'No se pudo registrar la venta. Inténtalo de nuevo.';
  }
}
