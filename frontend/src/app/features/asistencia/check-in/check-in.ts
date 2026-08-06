import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { AsistenciasService } from '../../../core/services/asistencias.service';
import { AuthService } from '../../../core/services/auth.service';
import { ClientesService } from '../../../core/services/clientes.service';
import { MembresiasService } from '../../../core/services/membresias.service';
import { PlanesService } from '../../../core/services/planes.service';
import { VentasService } from '../../../core/services/ventas.service';
import {
  Asistencia,
  RegistrarAsistenciaFormulario,
  VerificacionAsistencia,
} from '../../../core/models/asistencia.model';
import { ClienteResumen, EstadoFiltroCliente, EstadoMembresia } from '../../../core/models/cliente.model';
import { Plan } from '../../../core/models/plan.model';
import { ETIQUETAS_FORMA_PAGO, FormaPago } from '../../../core/models/venta.model';
import { formatearMonto, normalizarPrecio, precioParaMostrar, precioValido } from '../../../core/utils/precio.util';

/**
 * Estados de membresía con los que se puede pasar. Réplica de
 * `_ESTADOS_VIGENTES` del backend (`apps.asistencia.views`): sirve para
 * decidir si la fila del listado enseña el botón de registro directo, no
 * para autorizar nada -- quien decide sigue siendo el servidor.
 */
const ESTADOS_QUE_PERMITEN_PASAR: EstadoMembresia[] = ['activa', 'vence_hoy', 'por_vencer'];

/** Filtros rápidos del listado. El valor vacío no filtra. */
const FILTROS: { valor: EstadoFiltroCliente | ''; etiqueta: string }[] = [
  { valor: '', etiqueta: 'Todos' },
  { valor: 'activa', etiqueta: 'Con membresía' },
  { valor: 'por_vencer', etiqueta: 'Por vencer' },
  { valor: 'vencida', etiqueta: 'Vencida' },
  { valor: 'sin_membresia', etiqueta: 'Sin membresía' },
];

/**
 * Control de acceso (RF-15). Tres cosas separadas a propósito:
 *
 * 1. **Buscar** al cliente por nombre o cédula, sobre el listado de clientes
 *    (`/api/clientes/?buscar=`), no sobre la cédula exacta: en recepción se
 *    sabe el nombre mucho más a menudo que el número.
 * 2. **Verificar** (`/api/asistencias/verificar/`): informa y no deja rastro.
 * 3. **Registrar**: eso sí queda grabado.
 *
 * Si el cliente no puede pasar, la pantalla ofrece resolverlo en el momento
 * —renovar la membresía o cobrarle una sesión suelta— en vez de mandarlo a
 * otra pantalla y perder al cliente en el mostrador.
 *
 * Sin biometría: el lector no existe todavía.
 */
@Component({
  selector: 'app-asistencia-check-in',
  imports: [ReactiveFormsModule],
  templateUrl: './check-in.html',
})
export class AsistenciaCheckIn {
  private readonly asistenciasService = inject(AsistenciasService);
  private readonly clientesService = inject(ClientesService);
  private readonly membresiasService = inject(MembresiasService);
  private readonly ventasService = inject(VentasService);
  private readonly planesService = inject(PlanesService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeRegistrar = computed(() => this.authService.tienePermiso('ventas.registrar'));
  protected readonly puedeAutorizar = computed(() => this.authService.tienePermiso('asistencia.autorizar'));
  protected readonly puedeVerHistorial = computed(() => this.authService.tienePermiso('reportes.ver'));
  protected readonly puedeGestionarMembresias = computed(() =>
    this.authService.tienePermiso('membresias.gestionar'),
  );

  protected readonly filtros = FILTROS;
  protected readonly formasPago = ETIQUETAS_FORMA_PAGO;
  protected readonly opcionesFormaPago = Object.keys(ETIQUETAS_FORMA_PAGO) as FormaPago[];

  // --- Listado de clientes ---
  protected readonly busqueda = this.fb.nonNullable.control('');
  protected readonly filtroEstado = this.fb.nonNullable.control<EstadoFiltroCliente | ''>('');
  protected readonly clientes = signal<ClienteResumen[]>([]);
  protected readonly totalClientes = signal(0);
  protected readonly cargandoClientes = signal(true);
  protected readonly errorClientes = signal<string | null>(null);

  // --- Verificación del cliente elegido ---
  protected readonly verificacion = signal<VerificacionAsistencia | null>(null);
  protected readonly verificando = signal(false);
  protected readonly errorVerificar = signal<string | null>(null);

  // --- Registro del ingreso ---
  protected readonly registrando = signal(false);
  /** Id del cliente cuyo ingreso se está registrando DESDE EL LISTADO, para
   * poner solo esa fila en espera y no todas. */
  protected readonly registrandoId = signal<number | null>(null);
  protected readonly errorRegistrar = signal<string | null>(null);
  /** Separado de `errorRegistrar`: el antipassback NO es un fallo, así que se
   * presenta como aviso y no en rojo de error. */
  protected readonly avisoAntipassback = signal<string | null>(null);
  protected readonly ultimoRegistro = signal<Asistencia | null>(null);

  protected readonly formAutorizacion = this.fb.nonNullable.group({
    motivo_autorizacion: this.fb.nonNullable.control('', [Validators.required]),
  });

  // --- Resolver en el mostrador: renovar o cobrar una sesión suelta ---
  protected readonly accion = signal<'ninguna' | 'renovar' | 'sesion'>('ninguna');
  protected readonly procesandoAccion = signal(false);
  protected readonly errorAccion = signal<string | null>(null);
  /** Venta de la sesión recién cobrada. Mientras exista, el ingreso se
   * registra citándola como motivo. */
  protected readonly ventaSesion = signal<number | null>(null);

  protected readonly formRenovar = this.fb.nonNullable.group({
    plan_id: this.fb.nonNullable.control<number | ''>(''),
    precio_pagado: this.fb.nonNullable.control('', [Validators.required, precioValido]),
  });

  protected readonly formSesion = this.fb.nonNullable.group({
    plan_id: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    monto: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    forma_pago: this.fb.nonNullable.control<FormaPago | ''>('', [Validators.required]),
  });

  protected readonly planes = signal<Plan[]>([]);
  /** Los que generan membresía (para renovar). */
  protected readonly planesConVigencia = computed(() => this.planes().filter((p) => p.tipo !== 'por_sesion'));
  /** Los de sesión suelta (para cobrar una entrada puntual). */
  protected readonly planesPorSesion = computed(() => this.planes().filter((p) => p.tipo === 'por_sesion'));

  /** La membresía más reciente del cliente, que es la que se renueva. `null`
   * si nunca tuvo ninguna: entonces no hay nada que renovar y solo cabe
   * venderle una membresía nueva desde su ficha, o cobrarle una sesión. */
  protected readonly membresiaARenovar = computed(() => {
    const membresias = this.verificacion()?.membresias ?? [];
    return membresias.find((m) => m.estado_calculado !== 'cancelada') ?? null;
  });

  // --- Sesión suelta: cobrar una entrada puntual y dejar pasar ---
  //
  // Existe para el caso que ninguna otra pantalla cubre: alguien que NO es
  // cliente y quiere entrar una vez. Antes había que darlo de alta con
  // nombre, cédula, teléfono y dirección para cobrarle 5.000, lo cual no
  // tiene sentido.
  protected readonly panelSesionSuelta = signal(false);
  protected readonly procesandoSuelta = signal(false);
  protected readonly errorSuelta = signal<string | null>(null);

  protected readonly formSuelta = this.fb.nonNullable.group({
    plan_id: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    monto: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    forma_pago: this.fb.nonNullable.control<FormaPago | ''>('efectivo', [Validators.required]),
  });

  /** Cliente OPCIONAL de la sesión suelta. Identificarlo es lo que da
   * trazabilidad; dejarlo vacío es el caso del visitante de la calle. */
  protected readonly clienteSuelta = signal<ClienteResumen | null>(null);
  protected readonly buscarClienteSuelta = this.fb.nonNullable.control('');
  protected readonly sugerenciasSuelta = signal<ClienteResumen[]>([]);

  protected readonly historial = signal<Asistencia[]>([]);
  protected readonly cargandoHistorial = signal(false);

  constructor() {
    this.planesService.listar().subscribe({
      next: (planes) => this.planes.set(planes),
      error: () => this.planes.set([]),
    });

    this.busqueda.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.cargarClientes());

    this.filtroEstado.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.cargarClientes());

    this.buscarClienteSuelta.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((texto) => {
        const limpio = texto.trim();
        if (limpio.length < 2) {
          this.sugerenciasSuelta.set([]);
          return;
        }
        this.clientesService.listar(limpio).subscribe({
          next: (r) => this.sugerenciasSuelta.set(r.results.slice(0, 5)),
          error: () => this.sugerenciasSuelta.set([]),
        });
      });

    this.cargarClientes();
    if (this.puedeVerHistorial()) {
      this.cargarHistorial();
    }
  }

  // -----------------------------------------------------------------------
  // Listado y selección
  // -----------------------------------------------------------------------

  private cargarClientes(): void {
    this.cargandoClientes.set(true);
    this.errorClientes.set(null);
    const texto = this.busqueda.value.trim() || undefined;
    const estado = this.filtroEstado.value || undefined;

    this.clientesService.listar(texto, 1, estado).subscribe({
      next: (respuesta) => {
        this.clientes.set(respuesta.results);
        this.totalClientes.set(respuesta.count);
        this.cargandoClientes.set(false);
      },
      error: () => {
        this.clientes.set([]);
        this.cargandoClientes.set(false);
        this.errorClientes.set('No se pudo cargar el listado de clientes.');
      },
    });
  }

  /** `true` si la fila puede registrar el ingreso de un solo clic, sin pasar
   * por la verificación: su membresía está vigente y no hay nada que
   * decidir. Los demás casos sí exigen mirar el panel. */
  protected puedeIngresarDirecto(cliente: ClienteResumen): boolean {
    const estado = cliente.membresia_vigente?.estado_calculado;
    return estado !== undefined && ESTADOS_QUE_PERMITEN_PASAR.includes(estado);
  }

  /**
   * Registro de un clic desde el listado. `stopPropagation` es
   * imprescindible: sin él, el clic burbujearía al botón de la fila y además
   * abriría la verificación del cliente.
   *
   * El antipassback NO se comprueba aquí: el listado no sabe cuándo entró
   * cada quien por última vez. Lo resuelve el servidor con un 409 y se
   * muestra como aviso, no como error.
   */
  protected registrarDirecto(cliente: ClienteResumen, evento: Event): void {
    evento.stopPropagation();
    if (this.registrandoId() !== null) {
      return;
    }
    this.registrandoId.set(cliente.id);
    this.errorRegistrar.set(null);
    this.avisoAntipassback.set(null);
    this.ultimoRegistro.set(null);

    this.asistenciasService.registrar({ metodo: 'manual_cedula', cedula: cliente.cedula }).subscribe({
      next: (asistencia) => {
        this.registrandoId.set(null);
        this.ultimoRegistro.set(asistencia);
        if (this.puedeVerHistorial()) {
          this.cargarHistorial();
        }
        this.cargarClientes();
      },
      error: (error: unknown) => {
        this.registrandoId.set(null);
        if (error instanceof HttpErrorResponse && error.status === 409) {
          this.avisoAntipassback.set(
            this.mensajeDeError(error, `${cliente.nombre} ya registró un ingreso hace muy poco.`),
          );
          return;
        }
        this.errorRegistrar.set(this.mensajeDeError(error, 'No se pudo registrar el ingreso.'));
      },
    });
  }

  protected seleccionar(cliente: ClienteResumen): void {
    this.limpiarResultado();
    this.verificando.set(true);

    // `verificar` sigue pidiendo la cédula: la búsqueda por nombre se hace
    // contra el listado de clientes y de ahí sale la cédula exacta.
    this.asistenciasService.verificar(cliente.cedula).subscribe({
      next: (datos) => {
        this.verificando.set(false);
        this.verificacion.set(datos);
        this.formAutorizacion.reset({ motivo_autorizacion: '' });
      },
      error: (error: unknown) => {
        this.verificando.set(false);
        this.errorVerificar.set(this.mensajeDeError(error, 'No se pudo verificar al cliente.'));
      },
    });
  }

  protected volverAlListado(): void {
    this.limpiarResultado();
    this.cargarClientes();
  }

  // -----------------------------------------------------------------------
  // Resolver en el mostrador
  // -----------------------------------------------------------------------

  protected abrirRenovar(): void {
    const membresia = this.membresiaARenovar();
    const plan = this.planes().find((p) => p.id === membresia?.plan_id);
    this.errorAccion.set(null);
    this.formRenovar.reset({ plan_id: '', precio_pagado: plan ? formatearMonto(plan.precio) : '' });
    this.accion.set('renovar');
  }

  protected abrirSesion(): void {
    const plan = this.planesPorSesion()[0];
    this.errorAccion.set(null);
    this.formSesion.reset({
      plan_id: plan?.id ?? '',
      monto: plan ? formatearMonto(plan.precio) : '',
      forma_pago: 'efectivo',
    });
    this.accion.set('sesion');
  }

  protected cerrarAccion(): void {
    this.accion.set('ninguna');
    this.errorAccion.set(null);
  }

  /** Renueva y vuelve a verificar: si todo fue bien, el panel pasa a verde y
   * el ingreso ya no necesita autorización. */
  protected renovar(): void {
    const membresia = this.membresiaARenovar();
    const cliente = this.verificacion()?.cliente;
    if (this.procesandoAccion() || !membresia || !cliente) {
      return;
    }
    this.formRenovar.markAllAsTouched();
    if (this.formRenovar.invalid) {
      return;
    }

    const valores = this.formRenovar.getRawValue();
    this.procesandoAccion.set(true);
    this.errorAccion.set(null);

    this.membresiasService
      .renovar(membresia.id, {
        precio_pagado: normalizarPrecio(valores.precio_pagado) ?? '0',
        ...(valores.plan_id === '' ? {} : { plan_id: Number(valores.plan_id) }),
      })
      .subscribe({
        next: () => {
          this.procesandoAccion.set(false);
          this.accion.set('ninguna');
          this.reverificar(cliente.cedula);
        },
        error: (error: unknown) => {
          this.procesandoAccion.set(false);
          this.errorAccion.set(this.mensajeDeError(error, 'No se pudo renovar la membresía.'));
        },
      });
  }

  /**
   * Cobra una sesión suelta: venta + pago a nombre del cliente.
   *
   * NO usa el método `sesion_anonima` del backend, que existe para quien no
   * está identificado: aquí sabemos quién es, y con ese método la asistencia
   * quedaría sin `cliente` y no aparecería en su historial. Se registra como
   * ingreso normal con el motivo citando la venta, así que la entrada, el
   * cobro y la razón quedan los tres ligados al cliente.
   */
  protected cobrarSesion(): void {
    const cliente = this.verificacion()?.cliente;
    const sedeId = this.authService.sedeActual()?.id;
    if (this.procesandoAccion() || !cliente) {
      return;
    }
    if (sedeId === undefined) {
      this.errorAccion.set('Tu usuario no tiene una sede asignada; no se puede registrar la venta.');
      return;
    }
    this.formSesion.markAllAsTouched();
    if (this.formSesion.invalid) {
      return;
    }

    const valores = this.formSesion.getRawValue();
    this.procesandoAccion.set(true);
    this.errorAccion.set(null);

    this.ventasService
      .registrar({
        sede_id: sedeId,
        cliente_id: cliente.id,
        items: [{ tipo_item: 'plan', plan_id: Number(valores.plan_id), cantidad: '1' }],
        forma_pago: valores.forma_pago as FormaPago,
        monto_pago_inicial: normalizarPrecio(valores.monto) ?? '0',
      })
      .subscribe({
        next: (venta) => {
          this.procesandoAccion.set(false);
          this.accion.set('ninguna');
          this.ventaSesion.set(venta.id);
          // El motivo se rellena solo: quien cobra no debería tener que
          // redactar por qué deja pasar a alguien que acaba de pagar.
          this.formAutorizacion.setValue({
            motivo_autorizacion: `Sesión suelta pagada (venta #${venta.id})`,
          });
        },
        error: (error: unknown) => {
          this.procesandoAccion.set(false);
          this.errorAccion.set(this.mensajeDeError(error, 'No se pudo registrar el cobro de la sesión.'));
        },
      });
  }

  private reverificar(cedula: string): void {
    this.verificando.set(true);
    this.asistenciasService.verificar(cedula).subscribe({
      next: (datos) => {
        this.verificando.set(false);
        this.verificacion.set(datos);
      },
      error: (error: unknown) => {
        this.verificando.set(false);
        this.errorVerificar.set(this.mensajeDeError(error, 'No se pudo verificar al cliente.'));
      },
    });
  }

  // -----------------------------------------------------------------------
  // Sesión suelta
  // -----------------------------------------------------------------------

  protected abrirSesionSuelta(): void {
    this.limpiarResultado();
    const plan = this.planesPorSesion()[0];
    this.formSuelta.reset({
      plan_id: plan?.id ?? '',
      monto: plan ? formatearMonto(plan.precio) : '',
      forma_pago: 'efectivo',
    });
    this.clienteSuelta.set(null);
    this.buscarClienteSuelta.setValue('', { emitEvent: false });
    this.sugerenciasSuelta.set([]);
    this.errorSuelta.set(null);
    this.panelSesionSuelta.set(true);
  }

  protected cerrarSesionSuelta(): void {
    this.panelSesionSuelta.set(false);
    this.errorSuelta.set(null);
  }

  protected elegirClienteSuelta(cliente: ClienteResumen): void {
    this.clienteSuelta.set(cliente);
    this.sugerenciasSuelta.set([]);
    this.buscarClienteSuelta.setValue('', { emitEvent: false });
  }

  protected quitarClienteSuelta(): void {
    this.clienteSuelta.set(null);
  }

  /**
   * Cobra la sesión y registra el ingreso, en un solo gesto.
   *
   * Son DOS caminos según si se identificó al cliente, y la diferencia
   * importa:
   *
   * - **Sin cliente** → venta de mostrador y asistencia `sesion_anonima`.
   *   No exige `asistencia.autorizar`, porque no hay nadie a quien atribuir
   *   la entrada: el backend solo pide autorización cuando SÍ hay cliente
   *   identificado sin membresía vigente. El precio es que la entrada no
   *   queda ligada a nadie ni le aplica el antipassback.
   * - **Con cliente** → venta a su nombre y asistencia `manual_cedula` con
   *   el motivo citando la venta, de modo que aparezca en su historial.
   *
   * La venta y la asistencia son DOS peticiones: si la segunda falla, el
   * cobro ya está hecho y se dice, en vez de dejar creer que no pasó nada.
   */
  protected cobrarSesionSuelta(): void {
    const sedeId = this.authService.sedeActual()?.id;
    if (this.procesandoSuelta()) {
      return;
    }
    if (sedeId === undefined) {
      this.errorSuelta.set('Tu usuario no tiene una sede asignada; no se puede registrar la venta.');
      return;
    }
    this.formSuelta.markAllAsTouched();
    if (this.formSuelta.invalid) {
      return;
    }

    const cliente = this.clienteSuelta();
    const usuarioId = this.authService.sesion()?.id;
    if (cliente !== null && (!this.puedeAutorizar() || usuarioId === undefined)) {
      this.errorSuelta.set(
        'Identificar al cliente exige el permiso para autorizar ingresos sin membresía. ' +
          'Quita el cliente para cobrarla como sesión anónima, o pide a un responsable que la registre.',
      );
      return;
    }

    const valores = this.formSuelta.getRawValue();
    this.procesandoSuelta.set(true);
    this.errorSuelta.set(null);

    this.ventasService
      .registrar({
        sede_id: sedeId,
        ...(cliente ? { cliente_id: cliente.id } : {}),
        items: [{ tipo_item: 'plan', plan_id: Number(valores.plan_id), cantidad: '1' }],
        forma_pago: valores.forma_pago as FormaPago,
        monto_pago_inicial: normalizarPrecio(valores.monto) ?? '0',
      })
      .subscribe({
        next: (venta) => {
          const entrada: RegistrarAsistenciaFormulario = cliente
            ? {
                metodo: 'manual_cedula',
                cedula: cliente.cedula,
                autorizado_por_id: usuarioId,
                motivo_autorizacion: `Sesión suelta pagada (venta #${venta.id})`,
              }
            : { metodo: 'sesion_anonima', venta_id: venta.id };

          this.asistenciasService.registrar(entrada).subscribe({
            next: (asistencia) => {
              this.procesandoSuelta.set(false);
              this.panelSesionSuelta.set(false);
              this.ultimoRegistro.set(asistencia);
              if (this.puedeVerHistorial()) {
                this.cargarHistorial();
              }
            },
            error: (error: unknown) => {
              this.procesandoSuelta.set(false);
              // El cobro YA se hizo: ocultarlo llevaría a cobrar dos veces.
              this.errorSuelta.set(
                `La sesión se cobró (venta #${venta.id}), pero no se pudo registrar el ingreso: ` +
                  `${this.mensajeDeError(error, 'error desconocido')}. Déjale pasar y regístralo aparte.`,
              );
            },
          });
        },
        error: (error: unknown) => {
          this.procesandoSuelta.set(false);
          this.errorSuelta.set(this.mensajeDeError(error, 'No se pudo cobrar la sesión.'));
        },
      });
  }

  // -----------------------------------------------------------------------
  // Registro del ingreso
  // -----------------------------------------------------------------------

  protected registrarIngreso(): void {
    const datos = this.verificacion();
    if (datos === null || this.registrando()) {
      return;
    }

    let autorizacion = {};
    if (datos.requiere_autorizacion) {
      this.formAutorizacion.markAllAsTouched();
      if (this.formAutorizacion.invalid) {
        return;
      }
      const usuarioId = this.authService.sesion()?.id;
      if (usuarioId === undefined) {
        this.errorRegistrar.set('No se pudo identificar al usuario que autoriza. Vuelve a iniciar sesión.');
        return;
      }
      autorizacion = {
        autorizado_por_id: usuarioId,
        motivo_autorizacion: this.formAutorizacion.getRawValue().motivo_autorizacion.trim(),
      };
    }

    this.registrando.set(true);
    this.errorRegistrar.set(null);
    this.avisoAntipassback.set(null);

    this.asistenciasService
      .registrar({ metodo: 'manual_cedula', cedula: datos.cliente.cedula, ...autorizacion })
      .subscribe({
        next: (asistencia) => {
          this.registrando.set(false);
          this.ultimoRegistro.set(asistencia);
          this.verificacion.set(null);
          this.ventaSesion.set(null);
          if (this.puedeVerHistorial()) {
            this.cargarHistorial();
          }
          this.cargarClientes();
        },
        error: (error: unknown) => {
          this.registrando.set(false);
          // 409 = antipassback. El backend lo separa del 400 justamente para
          // que la interfaz no lo presente como un fallo.
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.avisoAntipassback.set(
              this.mensajeDeError(error, 'Este cliente ya registró un ingreso hace muy poco.'),
            );
            return;
          }
          this.errorRegistrar.set(this.mensajeDeError(error, 'No se pudo registrar el ingreso.'));
        },
      });
  }

  protected irAlCliente(): void {
    const cliente = this.verificacion()?.cliente;
    if (cliente) {
      this.router.navigate(['/clientes', cliente.id]);
    }
  }

  // -----------------------------------------------------------------------
  // Presentación
  // -----------------------------------------------------------------------

  protected nombrePlan(planId: number): string {
    return this.planes().find((p) => p.id === planId)?.nombre ?? `Plan #${planId}`;
  }

  protected dinero(valor: string): string {
    return precioParaMostrar(valor);
  }

  protected iniciales(nombre: string): string {
    const partes = nombre.trim().split(/\s+/).filter(Boolean);
    if (partes.length === 0) {
      return '?';
    }
    if (partes.length === 1) {
      return partes[0].charAt(0).toUpperCase();
    }
    return (partes[0].charAt(0) + partes[partes.length - 1].charAt(0)).toUpperCase();
  }

  protected claseEstado(estado: EstadoMembresia | undefined): string {
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

  protected etiquetaEstado(estado: EstadoMembresia | undefined): string {
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
        return 'Sin membresía';
    }
  }

  protected hora(iso: string): string {
    const fecha = new Date(iso);
    if (Number.isNaN(fecha.getTime())) {
      return iso;
    }
    return fecha.toLocaleString('es-CO', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  }

  private limpiarResultado(): void {
    this.verificacion.set(null);
    this.errorVerificar.set(null);
    this.errorRegistrar.set(null);
    this.avisoAntipassback.set(null);
    this.ultimoRegistro.set(null);
    this.accion.set('ninguna');
    this.errorAccion.set(null);
    this.ventaSesion.set(null);
  }

  private cargarHistorial(): void {
    this.cargandoHistorial.set(true);
    this.asistenciasService.listar().subscribe({
      next: (respuesta) => {
        this.historial.set(respuesta.results);
        this.cargandoHistorial.set(false);
      },
      error: () => {
        this.historial.set([]);
        this.cargandoHistorial.set(false);
      },
    });
  }

  private mensajeDeError(error: unknown, porDefecto: string): string {
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
    return porDefecto;
  }
}
