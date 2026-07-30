import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { CopCurrencyPipe } from '../../core/pipes/cop-currency.pipe';
import { AuthService } from '../../core/services/auth.service';
import { ClientesService } from '../../core/services/clientes.service';
import { PlanesService } from '../../core/services/planes.service';
import { ProductosService } from '../../core/services/productos.service';
import { VentasService } from '../../core/services/ventas.service';
import { ClienteResumen } from '../../core/models/cliente.model';
import { Plan } from '../../core/models/plan.model';
import { Producto } from '../../core/models/producto.model';
import { FormaPago, Venta, VentaCreateRequest } from '../../core/models/venta.model';
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

type Pestana = 'productos' | 'planes';

/**
 * Pantalla del POS (Parte B del encargo): buscador de producto siempre
 * visible, selector de planes, carrito editable, cliente opcional (obligado
 * ante pago parcial), descuento con motivo obligatorio si es > 0, y cobro en
 * la zona baja con forma de pago / monto recibido / total / saldo / cambio
 * en vivo.
 *
 * Estado: todo con signals (nada de BehaviorSubject propio) — el carrito es
 * la única fuente de verdad y los totales son `computed()` puros sobre él,
 * usando exactamente las mismas funciones (`carrito-calculo.ts`) que se
 * prueban por separado en `carrito-calculo.spec.ts`.
 */
@Component({
  selector: 'app-pos',
  standalone: true,
  imports: [FormsModule, CopCurrencyPipe],
  templateUrl: './pos.html',
  styleUrl: './pos.scss',
})
export class Pos implements OnInit {
  private readonly productosService = inject(ProductosService);
  private readonly planesService = inject(PlanesService);
  private readonly clientesService = inject(ClientesService);
  private readonly ventasService = inject(VentasService);
  protected readonly authService = inject(AuthService);

  /** Sede activa del usuario (`GET /api/auth/me/` -> `sedes[0]`), ya no
   * cableada por configuración (ver `environment`, ahora sin
   * `sedeIdPorDefecto`). TODO: cuando exista selector de sede, dejar de
   * asumir "la primera" (`AuthService.sedeActual`). */
  protected readonly sedeActual = this.authService.sedeActual;
  protected readonly puedeVender = computed(() => this.sedeActual() !== null);
  protected readonly puedeCobrarPermiso = computed(() =>
    this.authService.tienePermiso('ventas.registrar'),
  );

  // -- Catálogo -------------------------------------------------------
  protected readonly pestanaActiva = signal<Pestana>('productos');
  protected readonly textoBusquedaProducto = signal('');
  protected readonly resultadosProductos = signal<Producto[]>([]);
  protected readonly buscandoProductos = signal(false);
  private readonly busquedaProducto$ = new Subject<string>();

  protected readonly planes = signal<Plan[]>([]);
  protected readonly cargandoPlanes = signal(false);

  // -- Carrito ----------------------------------------------------------
  protected readonly lineas = signal<LineaCarrito[]>([]);

  protected readonly subtotal = computed(() => calcularSubtotal(this.lineas()));
  protected readonly total = computed(() => calcularTotal(this.subtotal(), this.descuentoMonto()));

  // -- Cliente ------------------------------------------------------------
  protected readonly textoBusquedaCliente = signal('');
  protected readonly resultadosClientes = signal<ClienteResumen[]>([]);
  protected readonly buscandoClientes = signal(false);
  protected readonly clienteSeleccionado = signal<ClienteResumen | null>(null);
  private readonly busquedaCliente$ = new Subject<string>();

  // -- Descuento ------------------------------------------------------------
  protected readonly descuentoMonto = signal(0);
  protected readonly motivoDescuento = signal('');
  protected readonly descuentoRequiereMotivo = computed(() =>
    requiereMotivoDescuento(this.descuentoMonto()),
  );
  protected readonly faltaMotivoDescuento = computed(
    () => this.descuentoRequiereMotivo() && this.motivoDescuento().trim().length === 0,
  );

  // -- Cobro ------------------------------------------------------------
  protected readonly formaPago = signal<FormaPago>('efectivo');
  protected readonly montoRecibido = signal(0);

  protected readonly saldoPendiente = computed(() =>
    calcularSaldoPendiente(this.total(), this.montoRecibido()),
  );
  protected readonly cambio = computed(() => calcularCambio(this.total(), this.montoRecibido()));
  protected readonly clienteEsObligatorio = computed(() =>
    requiereClientePorPago(this.total(), this.montoRecibido()),
  );
  protected readonly faltaCliente = computed(
    () => this.clienteEsObligatorio() && this.clienteSeleccionado() === null,
  );

  protected readonly puedeCobrar = computed(
    () =>
      this.puedeVender() &&
      this.puedeCobrarPermiso() &&
      this.lineas().length > 0 &&
      !this.faltaCliente() &&
      !this.faltaMotivoDescuento() &&
      !this.enviando(),
  );

  // -- Envío / resultado ------------------------------------------------------------
  protected readonly enviando = signal(false);
  protected readonly errorCobro = signal<string | null>(null);
  protected readonly ventaConfirmada = signal<Venta | null>(null);

  ngOnInit(): void {
    this.busquedaProducto$
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        switchMap((texto) => {
          const sede = this.sedeActual();
          if (!texto.trim() || sede === null) {
            this.buscandoProductos.set(false);
            return [];
          }
          this.buscandoProductos.set(true);
          return this.productosService.buscar(texto, sede.id);
        }),
      )
      .subscribe({
        next: (productos) => {
          this.buscandoProductos.set(false);
          this.resultadosProductos.set(productos);
        },
        error: () => this.buscandoProductos.set(false),
      });

    this.busquedaCliente$
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        switchMap((texto) => {
          if (!texto.trim()) {
            this.buscandoClientes.set(false);
            return [];
          }
          this.buscandoClientes.set(true);
          return this.clientesService.buscar(texto);
        }),
      )
      .subscribe({
        next: (clientes) => {
          this.buscandoClientes.set(false);
          this.resultadosClientes.set(clientes);
        },
        error: () => this.buscandoClientes.set(false),
      });

    this.cargandoPlanes.set(true);
    this.planesService.listar().subscribe({
      next: (planes) => {
        this.planes.set(planes);
        this.cargandoPlanes.set(false);
      },
      error: () => this.cargandoPlanes.set(false),
    });
  }

  seleccionarPestana(pestana: Pestana): void {
    this.pestanaActiva.set(pestana);
  }

  onBuscarProducto(texto: string): void {
    this.textoBusquedaProducto.set(texto);
    this.busquedaProducto$.next(texto);
  }

  onBuscarCliente(texto: string): void {
    this.textoBusquedaCliente.set(texto);
    this.busquedaCliente$.next(texto);
  }

  seleccionarCliente(cliente: ClienteResumen): void {
    this.clienteSeleccionado.set(cliente);
    this.textoBusquedaCliente.set('');
    this.resultadosClientes.set([]);
  }

  quitarCliente(): void {
    this.clienteSeleccionado.set(null);
  }

  /** Cantidad ya presente en el carrito para un producto dado (para topar el stock). */
  private cantidadEnCarritoDeProducto(productoId: number): number {
    return this.lineas()
      .filter((l) => l.tipoItem === 'producto' && l.productoId === productoId)
      .reduce((acc, l) => acc + l.cantidad, 0);
  }

  agregarProducto(producto: Producto): void {
    const stock = producto.stock !== null ? Number(producto.stock) : null;
    const yaEnCarrito = this.cantidadEnCarritoDeProducto(producto.id);
    const disponibles = unidadesDisponibles(stock, yaEnCarrito);

    if (disponibles <= 0) {
      this.errorCobro.set(`No hay más stock disponible de "${producto.nombre}".`);
      return;
    }

    const existente = this.lineas().find(
      (l) => l.tipoItem === 'producto' && l.productoId === producto.id,
    );

    if (existente) {
      this.cambiarCantidad(existente.idLocal, existente.cantidad + 1);
      return;
    }

    this.lineas.update((actuales) => [
      ...actuales,
      {
        idLocal: `producto-${producto.id}-${Date.now()}`,
        tipoItem: 'producto',
        productoId: producto.id,
        descripcion: producto.nombre,
        cantidad: 1,
        precioUnitario: Number(producto.precio_venta),
        stockDisponible: stock,
      },
    ]);
  }

  agregarPlan(plan: Plan): void {
    // Decisión del backend (services.py::registrar_venta): los planes con
    // vigencia (no "por_sesion") se venden de a una unidad por línea; una
    // segunda unidad del mismo plan es una línea nueva, no sumar cantidad.
    this.lineas.update((actuales) => [
      ...actuales,
      {
        idLocal: `plan-${plan.id}-${Date.now()}`,
        tipoItem: 'plan',
        planId: plan.id,
        descripcion: plan.nombre,
        cantidad: 1,
        precioUnitario: Number(plan.precio),
        stockDisponible: null,
      },
    ]);
  }

  cambiarCantidad(idLocal: string, nuevaCantidad: number): void {
    if (nuevaCantidad <= 0) {
      this.quitarLinea(idLocal);
      return;
    }

    this.lineas.update((actuales) =>
      actuales.map((linea) => {
        if (linea.idLocal !== idLocal) {
          return linea;
        }
        if (linea.stockDisponible !== null && nuevaCantidad > linea.stockDisponible) {
          this.errorCobro.set(
            `Solo hay ${linea.stockDisponible} unidades disponibles de "${linea.descripcion}".`,
          );
          return { ...linea, cantidad: linea.stockDisponible };
        }
        return { ...linea, cantidad: nuevaCantidad };
      }),
    );
  }

  incrementar(linea: LineaCarrito): void {
    this.cambiarCantidad(linea.idLocal, linea.cantidad + 1);
  }

  decrementar(linea: LineaCarrito): void {
    this.cambiarCantidad(linea.idLocal, linea.cantidad - 1);
  }

  quitarLinea(idLocal: string): void {
    this.lineas.update((actuales) => actuales.filter((l) => l.idLocal !== idLocal));
  }

  onDescuentoChange(valor: number): void {
    this.descuentoMonto.set(Math.max(valor || 0, 0));
  }

  onMontoRecibidoChange(valor: number): void {
    this.montoRecibido.set(Math.max(valor || 0, 0));
  }

  cobrar(): void {
    const sede = this.sedeActual();
    if (!this.puedeCobrar() || sede === null) {
      return;
    }

    this.errorCobro.set(null);
    this.enviando.set(true);

    const payload: VentaCreateRequest = {
      sede_id: sede.id,
      cliente_id: this.clienteSeleccionado()?.id ?? null,
      items: this.lineas().map((linea) => ({
        tipo_item: linea.tipoItem,
        ...(linea.tipoItem === 'producto'
          ? { producto_id: linea.productoId }
          : { plan_id: linea.planId }),
        cantidad: linea.cantidad,
      })),
      descuento: this.descuentoMonto(),
      motivo_descuento: this.descuentoMonto() > 0 ? this.motivoDescuento() : null,
      forma_pago: this.montoRecibido() > 0 ? this.formaPago() : null,
      monto_pago_inicial: this.montoRecibido(),
    };

    this.ventasService.registrar(payload).subscribe({
      next: (venta) => {
        this.enviando.set(false);
        this.ventaConfirmada.set(venta);
        this.reiniciarCarrito();
      },
      error: (error: unknown) => {
        this.enviando.set(false);
        this.errorCobro.set(this.extraerMensaje(error));
      },
    });
  }

  cerrarConfirmacion(): void {
    this.ventaConfirmada.set(null);
  }

  private reiniciarCarrito(): void {
    this.lineas.set([]);
    this.clienteSeleccionado.set(null);
    this.descuentoMonto.set(0);
    this.motivoDescuento.set('');
    this.montoRecibido.set(0);
    this.formaPago.set('efectivo');
    this.textoBusquedaProducto.set('');
    this.resultadosProductos.set([]);
  }

  /** El backend devuelve errores de negocio ya en español (400,
   * `{detail: "..."}` o `{campo: ["..."]}`, ver `apps/ventas/views.py` y
   * `serializers.py`): se muestran tal cual, sin envolverlos en "Error 400". */
  private extraerMensaje(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const cuerpo = error.error;
      if (cuerpo && typeof cuerpo === 'object') {
        if (typeof cuerpo.detail === 'string') {
          return cuerpo.detail;
        }
        const primerCampo = Object.values(cuerpo).find(
          (valor): valor is string[] => Array.isArray(valor) && valor.length > 0,
        );
        if (primerCampo) {
          return primerCampo[0];
        }
      }
      if (error.status === 0) {
        return 'No se pudo conectar con el servidor. Verifica tu conexión.';
      }
    }
    return 'Ocurrió un error inesperado al registrar la venta. Inténtalo de nuevo.';
  }
}
