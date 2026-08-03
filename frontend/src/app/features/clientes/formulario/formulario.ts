import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { environment } from '../../../../environments/environment';
import { ClientesService } from '../../../core/services/clientes.service';
import { SedesService } from '../../../core/services/sedes.service';
import { PlanesService } from '../../../core/services/planes.service';
import { Cliente, Sexo } from '../../../core/models/cliente.model';
import { SedeOrganizacion } from '../../../core/models/sede.model';
import { Plan, TipoPlan } from '../../../core/models/plan.model';

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
    // Autorizaciones (Ley 1581, solo alta).
    autoriza_tratamiento_datos: this.fb.nonNullable.control(false),
    autoriza_biometria: this.fb.nonNullable.control(false),
  });

  /** El plan elegido, o `null` si sigue en "Sin plan por ahora" (opción por
   * defecto: alguien puede registrarse hoy y pagar mañana). */
  protected readonly planSeleccionado = computed<Plan | null>(() => {
    const id = this.form.controls.planId.value;
    if (id === null) {
      return null;
    }
    return this.planes().find((p) => p.id === id) ?? null;
  });

  constructor() {
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
    if (!this.esEdicion && plan && !this.form.controls.formaPago.value) {
      this.errorGeneral.set('Selecciona una forma de pago para el plan elegido.');
      return;
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
    const cuerpoVenta = {
      sede_id: cliente.sede_origen,
      cliente_id: cliente.id,
      items: [{ tipo_item: 'plan', plan_id: plan.id, cantidad: '1' }],
      forma_pago: valores.formaPago,
      monto_pago_inicial: plan.precio,
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
