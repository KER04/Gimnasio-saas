import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { ClientesService } from '../../../core/services/clientes.service';
import { MembresiasService } from '../../../core/services/membresias.service';
import { PlanesService } from '../../../core/services/planes.service';
import { SedesService } from '../../../core/services/sedes.service';
import {
  AsistenciaCliente,
  Cliente,
  CompraCliente,
  DeudaCliente,
  MembresiaResumen,
} from '../../../core/models/cliente.model';
import { VentasService } from '../../../core/services/ventas.service';
import { Plan } from '../../../core/models/plan.model';
import { SedeOrganizacion } from '../../../core/models/sede.model';
import { ETIQUETAS_FORMA_PAGO, FormaPago } from '../../../core/models/venta.model';
import {
  formatearMonto,
  normalizarPrecio,
  precioParaMostrar,
  precioValido,
} from '../../../core/utils/precio.util';


/** Fecha de hoy en `YYYY-MM-DD`, la que espera `<input type="date">` y el
 * campo `fecha_inicio` del backend (mismo helper que `formulario.ts`). */
function hoyISO(): string {
  const hoy = new Date();
  const mes = String(hoy.getMonth() + 1).padStart(2, '0');
  const dia = String(hoy.getDate()).padStart(2, '0');
  return `${hoy.getFullYear()}-${mes}-${dia}`;
}

/**
 * Ficha del cliente (RF-03/RF-09/RF-16): datos personales, membresías, deuda,
 * compras y asistencias, TODO en una sola pantalla.
 *
 * Antes eran cinco pestañas que cargaban su endpoint al abrirse. Se
 * eliminaron: los datos de un cliente son pocos y se consultan juntos --
 * quien abre una ficha quiere saber si está al día Y cuánto debe--, así que
 * esconderlos detrás de cinco clics no ahorraba trabajo, lo añadía.
 */
@Component({
  selector: 'app-clientes-ficha',
  imports: [RouterLink, ReactiveFormsModule],
  templateUrl: './ficha.html',
})
export class ClientesFicha {
  private readonly clientesService = inject(ClientesService);
  private readonly membresiasService = inject(MembresiasService);
  private readonly ventasService = inject(VentasService);
  private readonly planesService = inject(PlanesService);
  private readonly sedesService = inject(SedesService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  private readonly clienteId = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('clientes.gestionar'));

  protected readonly puedeGestionarMembresias = computed(() =>
    this.authService.tienePermiso('membresias.gestionar'),
  );

  /** Vender y abonar son la MISMA autorización (`ventas.registrar`): las dos
   * mueven caja, a diferencia de la asignación directa de membresía. */
  protected readonly puedeCobrar = computed(() => this.authService.tienePermiso('ventas.registrar'));

  /** Anular exige un permiso propio y más alto: deshace dinero ya cobrado. */
  protected readonly puedeAnular = computed(() => this.authService.tienePermiso('ventas.anular'));

  // --- Anular una venta desde la deuda ---
  //
  // Vive aquí, y no solo en la pantalla de Ventas, porque este es el sitio
  // donde se DESCUBRE el problema: se ve una deuda que no debería existir.
  // Cancelar la membresía no la borra -- y es correcto que no lo haga, porque
  // cancelar revoca el acceso, no perdona lo consumido--; lo que la borra es
  // anular la venta, que además revierte pagos y stock.
  protected readonly ventaAnulando = signal<number | null>(null);
  protected readonly anulandoVenta = signal(false);
  protected readonly errorAnularVenta = signal<string | null>(null);
  protected readonly formAnularVenta = this.fb.nonNullable.group({
    motivo: this.fb.nonNullable.control('', [Validators.required]),
  });

  protected readonly cliente = signal<Cliente | null>(null);
  protected readonly cargandoCliente = signal(true);
  protected readonly errorCliente = signal<string | null>(null);



  // --- Membresías ---
  protected readonly membresias = signal<MembresiaResumen[] | null>(null);
  protected readonly cargandoMembresias = signal(false);
  protected readonly errorMembresias = signal<string | null>(null);

  // Catálogo y sedes: alimentan el selector de plan y permiten mostrar el
  // NOMBRE del plan y de la sede de cada membresía, en vez del id crudo.
  protected readonly planes = signal<Plan[]>([]);
  protected readonly sedes = signal<SedeOrganizacion[]>([]);

  protected readonly planesAsignables = computed(() =>
    this.planes().filter((plan) => plan.tipo !== 'por_sesion'),
  );

  /**
   * Añadir o renovar membresía: SIEMPRE por venta (RF-09).
   *
   * Es el único camino de la ficha, y no por simplificar la pantalla sino
   * porque los otros dos no cobraban de verdad:
   *
   * - `POST /api/membresias/` (asignación directa) crea la membresía con
   *   `venta = NULL`: no hay venta ni pago, el dinero no entra en caja.
   * - `POST /api/membresias/{id}/renovar/` hace lo mismo: pide
   *   `precio_pagado` pero tampoco genera venta, así que ese importe no
   *   aparece en los informes.
   *
   * `registrar_venta` en cambio crea venta + pago + membresía, admite pago
   * parcial (y por tanto abonos después) y YA ENCADENA la renovación por su
   * cuenta: si el cliente tiene una membresía activa del mismo plan sin
   * vencer, la nueva arranca donde terminaba la anterior, con el mismo
   * cálculo que el endpoint de renovar (`calcular_fechas_renovacion`).
   * Renovar, por tanto, es vender el mismo plan otra vez.
   */
  protected readonly panelVenderAbierto = signal(false);
  /** Membresía desde la que se abrió el panel, si vino de una fila. Solo
   * cambia el texto: el backend encadena mirando plan y fechas, no esto. */
  protected readonly renovandoDe = signal<MembresiaResumen | null>(null);
  protected readonly vendiendo = signal(false);
  protected readonly errorVender = signal<string | null>(null);

  protected readonly formasPago = ETIQUETAS_FORMA_PAGO;
  protected readonly opcionesFormaPago = Object.keys(ETIQUETAS_FORMA_PAGO) as FormaPago[];

  protected readonly formVender = this.fb.nonNullable.group({
    plan_id: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    fecha_inicio: this.fb.nonNullable.control(hoyISO(), [Validators.required]),
    /** Cuánto entrega el cliente AHORA. Puede ser 0 (queda a deber todo) o
     * el total (queda pagada); el backend valida que no supere el total. */
    monto_pago_inicial: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    forma_pago: this.fb.nonNullable.control<FormaPago | ''>(''),
  });

  private readonly planVentaId = toSignal(this.formVender.controls.plan_id.valueChanges, {
    initialValue: this.formVender.controls.plan_id.value,
  });
  private readonly montoInicialTexto = toSignal(this.formVender.controls.monto_pago_inicial.valueChanges, {
    initialValue: this.formVender.controls.monto_pago_inicial.value,
  });

  /** El plan que se está vendiendo. `FormControl.value` no es reactivo, de
   * ahí el `toSignal` (ver la nota larga en `formulario.ts`). */
  protected readonly planVenta = computed<Plan | null>(() => {
    const id = this.planVentaId();
    return id === '' || id === undefined ? null : (this.planes().find((p) => p.id === Number(id)) ?? null);
  });

  /** Saldo que quedará a deber tras la venta: total del plan menos lo que se
   * entrega ahora. Se muestra en vivo para que quien cobra vea la deuda que
   * está creando ANTES de confirmarla. `null` si aún no hay datos válidos. */
  protected readonly saldoTrasVenta = computed<string | null>(() => {
    const plan = this.planVenta();
    const abonado = normalizarPrecio(this.montoInicialTexto() ?? '');
    if (plan === null || abonado === null) {
      return null;
    }
    // En céntimos y con enteros: restar en coma flotante daría 0.009999...
    const saldoCentimos = Math.round(Number(plan.precio) * 100) - Math.round(Number(abonado) * 100);
    if (saldoCentimos < 0) {
      return null;
    }
    return (saldoCentimos / 100).toFixed(2);
  });

  /** `true` cuando lo que se entrega ahora supera el precio del plan: el
   * backend lo rechazaría, así que se avisa antes de enviar. */
  protected readonly montoInicialExcedido = computed<boolean>(() => {
    const plan = this.planVenta();
    const abonado = normalizarPrecio(this.montoInicialTexto() ?? '');
    if (plan === null || abonado === null) {
      return false;
    }
    return Math.round(Number(abonado) * 100) > Math.round(Number(plan.precio) * 100);
  });

  // --- Renovar / cancelar una membresía concreta ---
  // Son EXCLUYENTES entre sí y con el resto de paneles: solo un formulario
  // abierto a la vez, para que no haya dudas sobre a qué membresía se está
  // aplicando lo que se escribe.
  protected readonly membresiaCancelando = signal<number | null>(null);
  protected readonly procesandoMembresia = signal(false);
  protected readonly errorMembresiaAccion = signal<string | null>(null);

  protected readonly formCancelar = this.fb.nonNullable.group({
    motivo: this.fb.nonNullable.control('', [Validators.required]),
  });

  // --- Abonos sobre una venta con saldo ---
  protected readonly ventaAbonando = signal<number | null>(null);
  protected readonly abonando = signal(false);
  protected readonly errorAbono = signal<string | null>(null);

  protected readonly formAbono = this.fb.nonNullable.group({
    monto: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    forma_pago: this.fb.nonNullable.control<FormaPago | ''>('', [Validators.required]),
  });

  // --- Deuda ---
  protected readonly deuda = signal<DeudaCliente | null>(null);
  protected readonly cargandoDeuda = signal(false);
  protected readonly errorDeuda = signal<string | null>(null);

  // --- Compras ---
  protected readonly compras = signal<CompraCliente[] | null>(null);
  protected readonly cargandoCompras = signal(false);
  protected readonly errorCompras = signal<string | null>(null);
  protected readonly comprasCount = signal(0);
  protected readonly comprasNext = signal<string | null>(null);
  protected readonly comprasPrevious = signal<string | null>(null);
  protected readonly comprasPagina = signal(1);

  // --- Asistencias ---
  protected readonly asistencias = signal<AsistenciaCliente[] | null>(null);
  protected readonly cargandoAsistencias = signal(false);
  protected readonly errorAsistencias = signal<string | null>(null);
  protected readonly asistenciasCount = signal(0);
  protected readonly asistenciasNext = signal<string | null>(null);
  protected readonly asistenciasPrevious = signal<string | null>(null);
  protected readonly asistenciasPagina = signal(1);

  // --- Eliminar ---
  protected readonly confirmandoEliminar = signal(false);
  protected readonly eliminando = signal(false);
  protected readonly errorEliminar = signal<string | null>(null);

  constructor() {
    // Se carga TODO de entrada, no pestaña a pestaña: la ficha muestra ahora
    // el cliente entero en una sola pantalla. Son cinco peticiones pequeñas
    // sobre un mismo cliente, y salen en paralelo; a cambio se elimina la
    // navegación por pestañas y el "ya lo cargué" de cada una.
    this.cargarCliente();
    this.cargarMembresias();
    this.cargarDeuda();
    this.cargarCompras();
    this.cargarAsistencias();

    // Al elegir plan se propone su precio de catálogo como precio pagado.
    // Es una PROPUESTA, no una imposición: el campo queda editable porque
    // una cortesía o un traspaso pueden cobrarse a otro importe (o a cero),
    // que es justo para lo que sirve la asignación directa.
 }

  private cargarCliente(): void {
    this.cargandoCliente.set(true);
    this.errorCliente.set(null);
    this.clientesService.obtener(this.clienteId).subscribe({
      next: (cliente) => {
        this.cliente.set(cliente);
        this.cargandoCliente.set(false);
      },
      error: (error: unknown) => {
        this.cargandoCliente.set(false);
        this.errorCliente.set(this.mensajeDeError(error));
      },
    });
  }

  private cargarMembresias(): void {
    if (this.membresias() !== null || this.cargandoMembresias()) {
      return;
    }
    this.cargandoMembresias.set(true);
    this.errorMembresias.set(null);
    this.clientesService.membresias(this.clienteId).subscribe({
      next: (datos) => {
        this.membresias.set(datos);
        this.cargandoMembresias.set(false);
      },
      error: (error: unknown) => {
        this.cargandoMembresias.set(false);
        this.errorMembresias.set(this.mensajeDeError(error));
      },
    });

    // Catálogo y sedes: hacen falta para el selector de "Asignar membresía"
    // y, de paso, para poder mostrar el NOMBRE del plan de cada membresía en
    // vez del id crudo. Si fallan no se rompe la sección: solo se degrada a
    // "Plan #id" y el panel avisará de que no hay planes.
    if (this.planes().length === 0) {
      this.planesService.listar().subscribe({
        next: (planes) => this.planes.set(planes),
        error: () => this.planes.set([]),
      });
    }
    if (this.sedes().length === 0) {
      this.sedesService.listar().subscribe({
        next: (sedes) => this.sedes.set(sedes),
        error: () => this.sedes.set([]),
      });
    }
  }

  protected nombrePlan(planId: number): string {
    return this.planes().find((p) => p.id === planId)?.nombre ?? `Plan #${planId}`;
  }

  protected nombreSede(sedeId: number): string {
    return this.sedes().find((s) => s.id === sedeId)?.nombre ?? `Sede #${sedeId}`;
  }

  // -----------------------------------------------------------------------
  // Renovar y cancelar una membresía existente
  // -----------------------------------------------------------------------

  /** Una membresía cancelada no admite ninguna de las dos acciones: el
   * backend rechaza renovarla y rechaza cancelarla dos veces. */
  protected accionesDisponibles(membresia: MembresiaResumen): boolean {
    return this.puedeGestionarMembresias() && membresia.estado_calculado !== 'cancelada';
  }

  /**
   * Renovar es VENDER el mismo plan otra vez: abre el mismo panel con su plan
   * ya elegido. El encadenado (no perder días pagados) lo resuelve el backend
   * al crear la venta, comparando plan y fechas -- no depende de que se pulse
   * aquí y no allá.
   */
  protected abrirRenovar(membresia: MembresiaResumen): void {
    this.abrirVender(membresia.plan_id);
    this.renovandoDe.set(membresia);
  }

  protected abrirCancelar(membresia: MembresiaResumen): void {
    this.cerrarPanelesDeMembresia();
    this.formCancelar.reset({ motivo: '' });
    this.membresiaCancelando.set(membresia.id);
  }

  protected cerrarPanelesDeMembresia(): void {
    this.membresiaCancelando.set(null);
    this.errorMembresiaAccion.set(null);
  }

  protected cancelarMembresia(): void {
    const id = this.membresiaCancelando();
    if (this.procesandoMembresia() || id === null) {
      return;
    }
    this.formCancelar.markAllAsTouched();
    if (this.formCancelar.invalid) {
      return;
    }

    this.procesandoMembresia.set(true);
    this.errorMembresiaAccion.set(null);

    this.membresiasService
      .cancelar(id, { motivo: this.formCancelar.getRawValue().motivo.trim() })
      .subscribe({
        next: () => {
          this.procesandoMembresia.set(false);
          this.cerrarPanelesDeMembresia();
          this.recargarTrasMovimientoDeDinero();
        },
        error: (error: unknown) => {
          this.procesandoMembresia.set(false);
          this.errorMembresiaAccion.set(this.mensajeDeErrorAsignacion(error));
        },
      });
  }

  // -----------------------------------------------------------------------
  // Venta de membresía (pasa por caja) y abonos sobre el saldo
  // -----------------------------------------------------------------------

  protected dinero(valor: string): string {
    return precioParaMostrar(valor);
  }

  /** Cantidad de una línea sin decimales cuando son cero: el backend manda
   * `"1.00"` (es un Decimal) y en pantalla eso solo estorba. */
  protected cantidadItem(valor: string): string {
    const numero = Number(valor);
    return Number.isInteger(numero) ? String(numero) : valor;
  }

  /**
   * Fecha sola (`YYYY-MM-DD`) en formato legible.
   *
   * `T00:00:00` fuerza la interpretación en hora LOCAL: `new Date('2026-08-04')`
   * a secas se lee como UTC y en Colombia (UTC-5) mostraría el día anterior.
   */
  protected fechaCorta(iso: string | null): string {
    if (!iso) {
      return '—';
    }
    const fecha = new Date(`${iso}T00:00:00`);
    return Number.isNaN(fecha.getTime())
      ? iso
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  /** Fecha y hora de una marca de tiempo completa (ISO con zona). */
  protected fechaHora(iso: string | null): string {
    if (!iso) {
      return '—';
    }
    const fecha = new Date(iso);
    return Number.isNaN(fecha.getTime())
      ? iso
      : fecha.toLocaleString('es-CO', {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        });
  }

  protected etiquetaFormaPago(forma: string): string {
    return this.formasPago[forma as FormaPago] ?? forma;
  }

  /**
   * @param planId plan preseleccionado. Lo pasa "Renovar" desde una fila; la
   *   cabecera abre el panel sin plan para que se elija.
   */
  protected abrirVender(planId?: number): void {
    this.errorVender.set(null);
    this.renovandoDe.set(null);
    this.cerrarPanelesDeMembresia();

    const plan = planId === undefined ? null : this.planes().find((p) => p.id === planId);
    this.formVender.reset({
      plan_id: plan?.id ?? '',
      fecha_inicio: hoyISO(),
      // Se propone el precio ACTUAL del catálogo, no el que se pagó en su
      // día: renovar es una venta nueva y las tarifas suben.
      monto_pago_inicial: plan ? formatearMonto(plan.precio) : '',
      forma_pago: 'efectivo',
    });
    this.panelVenderAbierto.set(true);
  }

  protected cerrarVender(): void {
    this.panelVenderAbierto.set(false);
    this.renovandoDe.set(null);
    this.errorVender.set(null);
  }

  protected venderMembresia(): void {
    if (this.vendiendo()) {
      return;
    }
    this.formVender.markAllAsTouched();

    const plan = this.planVenta();
    const cliente = this.cliente();
    if (this.formVender.invalid || plan === null || cliente === null) {
      return;
    }
    if (this.montoInicialExcedido()) {
      this.errorVender.set('Lo que se paga ahora no puede superar el precio del plan.');
      return;
    }

    const valores = this.formVender.getRawValue();
    const montoInicial = normalizarPrecio(valores.monto_pago_inicial) ?? '0';
    const pagaAlgo = Number(montoInicial) > 0;

    // Regla del backend (`registrar_venta`): si entra dinero hay que decir
    // por qué vía. Con pago cero la forma de pago sobra y NO debe enviarse.
    if (pagaAlgo && valores.forma_pago === '') {
      this.formVender.controls.forma_pago.markAsTouched();
      this.errorVender.set('Indica la forma de pago del dinero que se recibe ahora.');
      return;
    }

    this.vendiendo.set(true);
    this.errorVender.set(null);

    this.ventasService
      .registrar({
        sede_id: cliente.sede_origen,
        cliente_id: cliente.id,
        items: [{ tipo_item: 'plan', plan_id: plan.id, cantidad: '1' }],
        ...(pagaAlgo ? { forma_pago: valores.forma_pago as FormaPago } : {}),
        monto_pago_inicial: montoInicial,
        fecha_inicio_membresia: valores.fecha_inicio,
      })
      .subscribe({
        next: () => {
          this.vendiendo.set(false);
          this.panelVenderAbierto.set(false);
          // La venta toca tres secciones: crea membresía, mueve la deuda
          // y añade una compra. Se invalidan las tres para que no queden
          // mostrando datos de antes de la venta.
          this.recargarTrasMovimientoDeDinero();
        },
        error: (error: unknown) => {
          this.vendiendo.set(false);
          this.errorVender.set(this.mensajeDeErrorAsignacion(error));
        },
      });
  }

  /** Abre el formulario de abono de UNA venta concreta, con el saldo
   * pendiente propuesto como monto (el caso corriente es saldar la deuda). */
  protected abrirAbono(ventaId: number, saldo: string): void {
    this.errorAbono.set(null);
    this.formAbono.reset({ monto: formatearMonto(saldo), forma_pago: '' });
    this.ventaAbonando.set(ventaId);
  }

  protected abrirAnularVenta(ventaId: number): void {
    this.cerrarAbono();
    this.errorAnularVenta.set(null);
    this.formAnularVenta.reset({ motivo: '' });
    this.ventaAnulando.set(ventaId);
  }

  protected cerrarAnularVenta(): void {
    this.ventaAnulando.set(null);
    this.errorAnularVenta.set(null);
  }

  protected anularVenta(): void {
    const id = this.ventaAnulando();
    if (this.anulandoVenta() || id === null) {
      return;
    }
    this.formAnularVenta.markAllAsTouched();
    if (this.formAnularVenta.invalid) {
      return;
    }

    this.anulandoVenta.set(true);
    this.errorAnularVenta.set(null);

    this.ventasService
      .anular(id, { motivo: this.formAnularVenta.getRawValue().motivo.trim() })
      .subscribe({
        next: () => {
          this.anulandoVenta.set(false);
          this.ventaAnulando.set(null);
          this.recargarTrasMovimientoDeDinero();
        },
        error: (error: unknown) => {
          this.anulandoVenta.set(false);
          this.errorAnularVenta.set(this.mensajeDeErrorAsignacion(error));
        },
      });
  }

  protected cerrarAbono(): void {
    this.ventaAbonando.set(null);
    this.errorAbono.set(null);
  }

  protected registrarAbono(saldo: string): void {
    const ventaId = this.ventaAbonando();
    if (this.abonando() || ventaId === null) {
      return;
    }
    this.formAbono.markAllAsTouched();
    if (this.formAbono.invalid) {
      return;
    }

    const valores = this.formAbono.getRawValue();
    const monto = normalizarPrecio(valores.monto) ?? '0';

    // Se adelanta a las dos reglas de `registrar_abono` que el usuario puede
    // corregir sin ir al servidor. El backend las revalida igualmente: es él
    // quien tiene el saldo bueno, este de aquí puede estar desactualizado si
    // alguien cobró desde otra pantalla mientras tanto.
    if (Number(monto) <= 0) {
      this.errorAbono.set('El monto del abono debe ser mayor que cero.');
      return;
    }
    if (Math.round(Number(monto) * 100) > Math.round(Number(saldo) * 100)) {
      this.errorAbono.set(`El abono no puede superar el saldo pendiente (${precioParaMostrar(saldo)}).`);
      return;
    }

    this.abonando.set(true);
    this.errorAbono.set(null);

    this.ventasService
      .abonar(ventaId, { monto, forma_pago: valores.forma_pago as FormaPago })
      .subscribe({
        next: () => {
          this.abonando.set(false);
          this.ventaAbonando.set(null);
          this.recargarTrasMovimientoDeDinero();
        },
        error: (error: unknown) => {
          this.abonando.set(false);
          this.errorAbono.set(this.mensajeDeErrorAsignacion(error));
        },
      });
  }

  /** Recarga las tres secciones que dependen del dinero. `cargarX` se salta
   * la petición si ya hay datos en memoria, así que ponerlos a `null` es lo
   * que fuerza el refresco. */
  private recargarTrasMovimientoDeDinero(): void {
    this.membresias.set(null);
    this.deuda.set(null);
    this.compras.set(null);
    this.cargarMembresias();
    this.cargarDeuda();
    this.cargarCompras();
  }

  /** Los errores de negocio de `asignar_membresia` (plan por sesión, precio
   * negativo) llegan como 400 con `{"detail": "..."}` o como diccionario de
   * campo; ambos traen texto ya en español, así que se muestran tal cual. */
  private mensajeDeErrorAsignacion(error: unknown): string {
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
    return 'No se pudo asignar la membresía. Inténtalo de nuevo.';
  }

  private cargarDeuda(): void {
    if (this.deuda() !== null || this.cargandoDeuda()) {
      return;
    }
    this.cargandoDeuda.set(true);
    this.errorDeuda.set(null);
    this.clientesService.deuda(this.clienteId).subscribe({
      next: (datos) => {
        this.deuda.set(datos);
        this.cargandoDeuda.set(false);
      },
      error: (error: unknown) => {
        this.cargandoDeuda.set(false);
        this.errorDeuda.set(this.mensajeDeError(error));
      },
    });
  }

  private cargarCompras(): void {
    if (this.compras() !== null || this.cargandoCompras()) {
      return;
    }
    this.cargandoCompras.set(true);
    this.errorCompras.set(null);
    this.clientesService.compras(this.clienteId, this.comprasPagina()).subscribe({
      next: (respuesta) => {
        this.compras.set(respuesta.results);
        this.comprasCount.set(respuesta.count);
        this.comprasNext.set(respuesta.next);
        this.comprasPrevious.set(respuesta.previous);
        this.cargandoCompras.set(false);
      },
      error: (error: unknown) => {
        this.cargandoCompras.set(false);
        this.errorCompras.set(this.mensajeDeError(error));
      },
    });
  }

  protected comprasSiguiente(): void {
    if (!this.comprasNext()) {
      return;
    }
    this.comprasPagina.update((p) => p + 1);
    this.compras.set(null);
    this.cargarCompras();
  }

  protected comprasAnterior(): void {
    if (!this.comprasPrevious()) {
      return;
    }
    this.comprasPagina.update((p) => Math.max(1, p - 1));
    this.compras.set(null);
    this.cargarCompras();
  }

  private cargarAsistencias(): void {
    if (this.asistencias() !== null || this.cargandoAsistencias()) {
      return;
    }
    this.cargandoAsistencias.set(true);
    this.errorAsistencias.set(null);
    this.clientesService.asistencias(this.clienteId, this.asistenciasPagina()).subscribe({
      next: (respuesta) => {
        this.asistencias.set(respuesta.results);
        this.asistenciasCount.set(respuesta.count);
        this.asistenciasNext.set(respuesta.next);
        this.asistenciasPrevious.set(respuesta.previous);
        this.cargandoAsistencias.set(false);
      },
      error: (error: unknown) => {
        this.cargandoAsistencias.set(false);
        this.errorAsistencias.set(this.mensajeDeError(error));
      },
    });
  }

  protected asistenciasSiguiente(): void {
    if (!this.asistenciasNext()) {
      return;
    }
    this.asistenciasPagina.update((p) => p + 1);
    this.asistencias.set(null);
    this.cargarAsistencias();
  }

  protected asistenciasAnterior(): void {
    if (!this.asistenciasPrevious()) {
      return;
    }
    this.asistenciasPagina.update((p) => Math.max(1, p - 1));
    this.asistencias.set(null);
    this.cargarAsistencias();
  }

  protected confirmarEliminar(): void {
    this.confirmandoEliminar.set(true);
  }

  protected cancelarEliminar(): void {
    this.confirmandoEliminar.set(false);
  }

  protected eliminar(): void {
    if (this.eliminando()) {
      return;
    }
    this.eliminando.set(true);
    this.errorEliminar.set(null);
    this.clientesService.eliminar(this.clienteId).subscribe({
      next: () => {
        this.router.navigate(['/clientes']);
      },
      error: (error: unknown) => {
        this.eliminando.set(false);
        this.errorEliminar.set(this.mensajeDeError(error));
      },
    });
  }

  protected badgeMembresia(estado: string): string {
    switch (estado) {
      case 'activa':
        return 'badge-success';
      case 'por_vencer':
      case 'vence_hoy':
        return 'badge-warning';
      case 'vencida':
        return 'badge-danger';
      default:
        return 'badge-neutral';
    }
  }

  protected etiquetaEstadoMembresia(estado: string): string {
    switch (estado) {
      case 'activa':
        return 'Activa';
      case 'por_vencer':
        return 'Por vencer';
      case 'vence_hoy':
        return 'Vence hoy';
      case 'vencida':
        return 'Vencida';
      case 'cancelada':
        return 'Cancelada';
      default:
        return estado;
    }
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo cargar la información. Inténtalo de nuevo.';
  }
}
