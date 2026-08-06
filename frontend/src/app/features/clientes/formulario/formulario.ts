import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { environment } from '../../../../environments/environment';
import { ClientesService } from '../../../core/services/clientes.service';
import { SedesService } from '../../../core/services/sedes.service';
import { PlanesService } from '../../../core/services/planes.service';
import { Cliente, Sexo } from '../../../core/models/cliente.model';
import { SedeOrganizacion } from '../../../core/models/sede.model';
import { Plan, TipoPlan } from '../../../core/models/plan.model';
import { formatearMonto, normalizarPrecio, precioValido } from '../../../core/utils/precio.util';

/** Errores de campo tal como los devuelve DRF: `{"campo": "texto" | ["texto", ...]}`. */
type ErroresDeCampo = Record<string, string | string[]>;

type FormaPago = 'efectivo' | 'transferencia';

const ETIQUETAS_TIPO_PLAN: Record<TipoPlan, string> = {
  mensual: 'Mensual',
  quincenal: 'Quincenal',
  por_sesion: 'Por sesión',
};

/** Fecha de hoy en formato `YYYY-MM-DD`, la que espera un `<input type="date">`
 * y el campo `fecha_inicio_membresia` del backend (`DateField`). */
function hoyISO(): string {
  const hoy = new Date();
  const mes = String(hoy.getMonth() + 1).padStart(2, '0');
  const dia = String(hoy.getDate()).padStart(2, '0');
  return `${hoy.getFullYear()}-${mes}-${dia}`;
}

/**
 * Alta y edición de clientes (RF-03). Misma pantalla para `/clientes/nuevo`
 * y `/clientes/{id}/editar`: en edición se precarga la ficha y se ocultan
 * la membresía, el pago y las autorizaciones (Ley 1581), que solo aplican
 * al crear.
 *
 * ## Guardado en el alta: DOS llamadas encadenadas
 *
 * 1. `POST /api/clientes/` con los datos personales.
 * 2. Solo si se eligió un plan (no "Sin plan por ahora"): `POST /api/ventas/`
 *    con ese plan como ítem, el cliente recién creado, la sede que el
 *    backend ya resolvió para el cliente (`cliente.sede_origen`), la forma
 *    de pago y el precio del plan como `monto_pago_inicial`. Esa venta es
 *    la que crea la membresía y registra el pago (`registrar_venta`,
 *    verificado contra el backend real).
 *
 * Si el paso 1 falla, no se sigue: se muestra el error y el cliente no
 * llegó a crearse. Si el paso 1 tuvo éxito y el paso 2 falla, el cliente YA
 * EXISTE -- ocultarlo llevaría a un alta duplicada -- así que se avisa con
 * un mensaje explícito (bloqueante, `alert()`: no hay ficha a la que
 * añadirle un banner sin tocar `features/clientes/ficha`, fuera de alcance)
 * y se navega igual a la ficha del cliente, donde puede vendérsele el plan
 * más tarde.
 */
@Component({
  selector: 'app-clientes-formulario',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './formulario.html',
})
export class ClientesFormulario {
  private readonly fb = inject(FormBuilder);
  private readonly clientesService = inject(ClientesService);
  private readonly sedesService = inject(SedesService);
  private readonly planesService = inject(PlanesService);
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  private readonly idParam = this.route.snapshot.paramMap.get('id');
  protected readonly clienteId = this.idParam ? Number(this.idParam) : null;
  protected readonly esEdicion = this.clienteId !== null;

  protected readonly sedes = signal<SedeOrganizacion[]>([]);
  protected readonly planes = signal<Plan[]>([]);
  protected readonly cargandoFicha = signal(this.esEdicion);
  protected readonly enviando = signal(false);
  protected readonly errorGeneral = signal<string | null>(null);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly titulo = computed(() => (this.esEdicion ? 'Editar cliente' : 'Nuevo cliente'));

  protected readonly form = this.fb.nonNullable.group({
    nombre: this.fb.nonNullable.control('', [Validators.required]),
    cedula: this.fb.nonNullable.control('', [Validators.required]),
    telefono: this.fb.nonNullable.control('', [Validators.required]),
    direccion: this.fb.nonNullable.control('', [Validators.required]),
    sexo: this.fb.nonNullable.control<Sexo | ''>(''),
    sede_origen: this.fb.nonNullable.control<number | ''>(''),
    // Membresía/pago (solo alta, ver plantilla: sección oculta en edición).
    planId: this.fb.control<number | null>(null),
    fechaInicio: this.fb.nonNullable.control(hoyISO()),
    formaPago: this.fb.nonNullable.control<FormaPago | ''>(''),
    /** Cuánto entrega el cliente HOY. Se propone el precio del plan, pero
     * puede rebajarse (incluso a cero): lo que no se pague queda como saldo
     * de la venta y se cobra después por abonos (RF-09). */
    montoInicial: this.fb.nonNullable.control('', [precioValido]),
    // Autorizaciones (Ley 1581, solo alta).
    autoriza_tratamiento_datos: this.fb.nonNullable.control(false),
    autoriza_biometria: this.fb.nonNullable.control(false),
  });

  /**
   * Espejo en señal del control `planId`.
   *
   * `FormControl.value` NO es una señal: el grafo reactivo de Angular no lo
   * observa. Un `computed` que lo leyera directamente solo se invalidaría
   * cuando cambiase alguna señal que sí lee (aquí `planes()`, que cambia una
   * única vez al cargar el catálogo, cuando `planId` todavía es `null`), y a
   * partir de ahí devolvería `null` PARA SIEMPRE por mucho que el usuario
   * eligiera un plan.
   *
   * No era un detalle teórico: con `planSeleccionado` clavado en `null`, la
   * sección de forma de pago nunca llegaba a mostrarse y el alta terminaba
   * creando el cliente SIN membresía, sin error ni aviso -- la tarjeta del
   * plan sí se veía resaltada, porque la plantilla compara contra
   * `form.controls.planId.value` en cada ciclo de detección de cambios, así
   * que todo aparentaba funcionar.
   */
  private readonly planIdSeleccionado = toSignal(this.form.controls.planId.valueChanges, {
    initialValue: this.form.controls.planId.value,
  });

  /** El plan elegido, o `null` si sigue en "Sin plan por ahora" (opción por
   * defecto: alguien puede registrarse hoy y pagar mañana). */
  protected readonly planSeleccionado = computed<Plan | null>(() => {
    const id = this.planIdSeleccionado();
    if (id === null || id === undefined) {
      return null;
    }
    return this.planes().find((p) => p.id === id) ?? null;
  });

  private readonly montoInicialTexto = toSignal(this.form.controls.montoInicial.valueChanges, {
    initialValue: this.form.controls.montoInicial.value,
  });

  /** Saldo que quedaría a deber: precio del plan menos lo que se paga hoy.
   * Se calcula en céntimos con enteros porque restar en coma flotante
   * produce residuos del tipo 0.009999999. `null` si aún no hay datos. */
  protected readonly saldoTrasAlta = computed<string | null>(() => {
    const plan = this.planSeleccionado();
    const abonado = normalizarPrecio(this.montoInicialTexto() ?? '');
    if (plan === null || abonado === null) {
      return null;
    }
    const centimos = Math.round(Number(plan.precio) * 100) - Math.round(Number(abonado) * 100);
    return centimos < 0 ? null : (centimos / 100).toFixed(2);
  });

  /** `true` si lo que se paga hoy supera el precio: el backend lo rechaza
   * (`registrar_venta`), así que se avisa antes de enviar. */
  protected readonly montoInicialExcedido = computed<boolean>(() => {
    const plan = this.planSeleccionado();
    const abonado = normalizarPrecio(this.montoInicialTexto() ?? '');
    if (plan === null || abonado === null) {
      return false;
    }
    return Math.round(Number(abonado) * 100) > Math.round(Number(plan.precio) * 100);
  });

  /** Espejo en señal de `fechaInicio`, por el mismo motivo que
   * `planIdSeleccionado`: `FormControl.value` no es reactivo. */
  private readonly fechaInicioSeleccionada = toSignal(this.form.controls.fechaInicio.valueChanges, {
    initialValue: this.form.controls.fechaInicio.value,
  });

  /**
   * Vencimiento previsto de la membresía, para no obligar a nadie a echar la
   * cuenta de cabeza antes de cobrar.
   *
   * Reproduce el mismo cálculo que hace el backend al crearla
   * (`fecha_fin = fecha_inicio + planes.duracion_dias`, ver
   * `apps.membresias.services`). Es una PREVISUALIZACIÓN: la fecha que vale
   * es la que devuelve el servidor. `null` cuando no hay plan con vigencia
   * (los planes por sesión no tienen `duracion_dias`) o la fecha es inválida.
   */
  protected readonly fechaFinPrevista = computed<string | null>(() => {
    const plan = this.planSeleccionado();
    const inicio = this.fechaInicioSeleccionada();
    if (plan === null || plan.duracion_dias === null || !inicio) {
      return null;
    }
    // `T00:00:00` fuerza la interpretación en hora LOCAL: `new Date('2026-08-03')`
    // a secas se interpreta como UTC y en Colombia (UTC-5) retrocedería un día.
    const fecha = new Date(`${inicio}T00:00:00`);
    if (Number.isNaN(fecha.getTime())) {
      return null;
    }
    fecha.setDate(fecha.getDate() + plan.duracion_dias);
    return fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'long', year: 'numeric' });
  });

  constructor() {
    // Al elegir plan se propone pagarlo entero, que es el caso corriente;
    // rebajarlo es lo que crea el saldo pendiente.
    this.form.controls.planId.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((planId) => {
        const plan = this.planes().find((p) => p.id === planId);
        this.form.controls.montoInicial.setValue(plan ? formatearMonto(plan.precio) : '');
      });

    this.sedesService.listar().subscribe({
      next: (sedes) => this.sedes.set(sedes),
      error: () => this.sedes.set([]),
    });

    if (!this.esEdicion) {
      this.planesService.listar().subscribe({
        next: (planes) => this.planes.set(planes),
        error: () => this.planes.set([]),
      });
    }

    if (this.clienteId !== null) {
      this.clientesService.obtener(this.clienteId).subscribe({
        next: (cliente) => {
          this.form.patchValue({
            nombre: cliente.nombre,
            cedula: cliente.cedula,
            telefono: cliente.telefono,
            direccion: cliente.direccion,
            sexo: cliente.sexo ?? '',
            sede_origen: cliente.sede_origen,
          });
          this.cargandoFicha.set(false);
        },
        error: (error: unknown) => {
          this.cargandoFicha.set(false);
          this.errorGeneral.set(this.mensajeGeneral(error));
        },
      });
    }
  }

  protected errorDe(campo: string): string | null {
    const valor = this.erroresCampo()[campo];
    if (!valor) {
      return null;
    }
    return Array.isArray(valor) ? valor[0] : valor;
  }

  protected etiquetaTipoPlan(tipo: TipoPlan): string {
    return ETIQUETAS_TIPO_PLAN[tipo] ?? tipo;
  }

  /** Precio en pesos colombianos, sin decimales y con separador de miles
   * (p. ej. `"50000.00"` -> `"$50.000"`). */
  protected formatearPrecio(precio: string): string {
    const valor = Number(precio);
    return new Intl.NumberFormat('es-CO', {
      style: 'currency',
      currency: 'COP',
      maximumFractionDigits: 0,
    }).format(valor);
  }

  /** Clase de una tarjeta seleccionable (plan o forma de pago): borde y
   * fondo tenue cuando está elegida, igual que en la referencia visual. */
  protected claseTarjetaSeleccionable(seleccionada: boolean, extra = ''): string {
    const base = `card-base transition-colors ${extra}`.trim();
    return seleccionada ? `${base} border-2 border-primary bg-primary-container/10` : base;
  }

  protected seleccionarPlan(id: number | null): void {
    this.form.controls.planId.setValue(id);
    if (id === null) {
      this.form.controls.formaPago.setValue('');
    }
  }

  protected enviar(): void {
    if (this.enviando()) {
      return;
    }

    this.form.markAllAsTouched();
    if (this.form.invalid) {
      return;
    }

    const plan = this.planSeleccionado();
    if (!this.esEdicion && plan) {
      if (this.montoInicialExcedido()) {
        this.errorGeneral.set('Lo que se paga hoy no puede superar el precio del plan.');
        return;
      }
      // La forma de pago solo hace falta si entra dinero: con pago cero la
      // venta nace `pendiente` y no hay nada que clasificar en caja (misma
      // regla que aplica `registrar_venta` en el backend).
      const pagaAlgo = Number(normalizarPrecio(this.form.controls.montoInicial.value) ?? '0') > 0;
      if (pagaAlgo && !this.form.controls.formaPago.value) {
        this.errorGeneral.set('Selecciona una forma de pago para el dinero que se recibe hoy.');
        return;
      }
    }

    this.errorGeneral.set(null);
    this.erroresCampo.set({});
    this.enviando.set(true);

    const valores = this.form.getRawValue();
    const payload = {
      nombre: valores.nombre.trim(),
      cedula: valores.cedula.trim(),
      telefono: valores.telefono.trim(),
      direccion: valores.direccion.trim(),
      sexo: valores.sexo || null,
      // La sede es opcional: si no se elige, se OMITE del cuerpo en vez de
      // mandarla en `null`. El backend deduce entonces la sede del usuario.
      // (También acepta `null`, pero omitirla expresa mejor "no la indico" y
      // deja el cuerpo más limpio.)
      ...(valores.sede_origen === '' ? {} : { sede_origen: valores.sede_origen }),
      ...(this.esEdicion
        ? {}
        : {
            autoriza_tratamiento_datos: valores.autoriza_tratamiento_datos,
            autoriza_biometria: valores.autoriza_biometria,
          }),
    };

    const peticion$ = this.esEdicion
      ? this.clientesService.actualizar(this.clienteId!, payload)
      : this.clientesService.crear(payload);

    peticion$.subscribe({
      next: (cliente) => {
        if (this.esEdicion || !plan) {
          this.enviando.set(false);
          this.router.navigate(['/clientes', cliente.id]);
          return;
        }
        this.registrarVentaDelPlan(cliente, plan);
      },
      error: (error: unknown) => {
        this.enviando.set(false);
        this.manejarError(error);
      },
    });
  }

  /** Paso 2 del alta (solo si se eligió un plan): registra la venta que crea
   * la membresía y el pago. El cliente del paso 1 YA EXISTE pase lo que
   * pase aquí -- ver el docstring de la clase. */
  private registrarVentaDelPlan(cliente: Cliente, plan: Plan): void {
    const valores = this.form.getRawValue();
    // Antes se mandaba `plan.precio` a fuego, así que toda venta nacía
    // pagada y era IMPOSIBLE que un cliente quedara debiendo. Ahora se manda
    // lo que se recibe de verdad: si es menos que el precio, la venta queda
    // con saldo y se cobra por abonos desde la ficha (RF-09).
    const montoInicial = normalizarPrecio(valores.montoInicial) ?? '0';
    const pagaAlgo = Number(montoInicial) > 0;

    const cuerpoVenta = {
      sede_id: cliente.sede_origen,
      cliente_id: cliente.id,
      items: [{ tipo_item: 'plan', plan_id: plan.id, cantidad: '1' }],
      // Con pago cero NO se envía forma de pago: el backend la rechaza como
      // incoherente (no hay dinero que clasificar).
      ...(pagaAlgo ? { forma_pago: valores.formaPago } : {}),
      monto_pago_inicial: montoInicial,
      fecha_inicio_membresia: valores.fechaInicio,
    };

    this.http.post(`${environment.apiUrl}/ventas/`, cuerpoVenta).subscribe({
      next: () => {
        this.enviando.set(false);
        this.router.navigate(['/clientes', cliente.id]);
      },
      error: () => {
        this.enviando.set(false);
        // El cliente ya se creó: no ocultarlo, avisar y seguir a su ficha
        // (ahí se le puede vender el plan más tarde). Ver docstring de clase.
        alert(
          'Se creó el cliente, pero no se pudo registrar el pago del plan. ' +
            'Puedes venderle el plan desde su ficha.',
        );
        this.router.navigate(['/clientes', cliente.id]);
      },
    });
  }

  private manejarError(error: unknown): void {
    if (error instanceof HttpErrorResponse && error.status === 400 && error.error) {
      const cuerpo = error.error as Record<string, unknown>;
      if (cuerpo['detail']) {
        this.errorGeneral.set(String(cuerpo['detail']));
        return;
      }
      // Diccionario de errores por campo (p. ej. cédula duplicada): se
      // muestran tal cual, en español, debajo de cada campo.
      this.erroresCampo.set(cuerpo as ErroresDeCampo);
      return;
    }
    this.errorGeneral.set(this.mensajeGeneral(error));
  }

  private mensajeGeneral(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo guardar el cliente. Inténtalo de nuevo.';
  }
}
