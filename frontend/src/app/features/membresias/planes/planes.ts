import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { AuthService } from '../../../core/services/auth.service';
import { PlanesService } from '../../../core/services/planes.service';
import { SedesService } from '../../../core/services/sedes.service';
import { Plan, PlanFormulario, TipoPlan } from '../../../core/models/plan.model';
import { SedeOrganizacion } from '../../../core/models/sede.model';
import { formatearMonto, normalizarPrecio, precioValido } from '../../../core/utils/precio.util';

/** Errores de campo tal como los devuelve DRF: `{"campo": "texto" | ["texto", ...]}`. */
type ErroresDeCampo = Record<string, string | string[]>;

const ETIQUETAS_TIPO_PLAN: Record<TipoPlan, string> = {
  mensual: 'Mensual',
  quincenal: 'Quincenal',
  por_sesion: 'Por sesión',
};

/**
 * Gestión de Membresías: catálogo de planes con CRUD completo (`/api/planes/`).
 * Tabla + panel lateral de creación/edición, en dos columnas en escritorio
 * y apilados en móvil (RF-23, sin scroll horizontal a 360px).
 *
 * El borrado es lógico ("dar de baja"): `Membresia.plan` protege el plan en
 * cuanto tiene una venta, así que un plan solo se saca del catálogo vendible
 * (`activo=false`), nunca se elimina la fila.
 */
@Component({
  selector: 'app-planes-listado',
  imports: [ReactiveFormsModule],
  templateUrl: './planes.html',
})
export class PlanesListado {
  private readonly fb = inject(FormBuilder);
  private readonly planesService = inject(PlanesService);
  private readonly sedesService = inject(SedesService);
  private readonly authService = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('membresias.gestionar'));

  protected readonly etiquetasTipo = ETIQUETAS_TIPO_PLAN;

  protected readonly planes = signal<Plan[]>([]);
  protected readonly sedes = signal<SedeOrganizacion[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly guardando = signal(false);
  protected readonly eliminandoId = signal<number | null>(null);
  protected readonly planEditando = signal<Plan | null>(null);
  protected readonly panelAbierto = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly titulo = computed(() => (this.planEditando() ? 'Editar Membresía' : 'Nueva Membresía'));

  protected readonly form = this.fb.nonNullable.group({
    nombre: this.fb.nonNullable.control('', [Validators.required]),
    precio: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    tipo: this.fb.nonNullable.control<TipoPlan>('mensual', [Validators.required]),
    duracion_dias: this.fb.nonNullable.control<number | null>(30, [Validators.required, Validators.min(1)]),
    sede: this.fb.nonNullable.control<number | ''>(''),
    requiere_entrenador: this.fb.nonNullable.control(false),
    activo: this.fb.nonNullable.control(true),
  });

  constructor() {
    this.sedesService.listar().subscribe({
      next: (sedes) => this.sedes.set(sedes),
      error: () => this.sedes.set([]),
    });

    // ck_planes_duracion: los planes "por sesión" no tienen duración. El
    // campo se oculta y se deja de exigir cuando se elige ese tipo, y se
    // vuelve a exigir (mínimo 1 día) para el resto.
    this.form.controls.tipo.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((tipo) => {
      const duracion = this.form.controls.duracion_dias;
      if (tipo === 'por_sesion') {
        duracion.setValue(null);
        duracion.clearValidators();
      } else {
        duracion.setValidators([Validators.required, Validators.min(1)]);
        if (!duracion.value) {
          duracion.setValue(30);
        }
      }
      duracion.updateValueAndValidity();
    });

    this.cargar();
  }

  private cargar(): void {
    this.cargando.set(true);
    this.error.set(null);

    this.planesService.listarTodos().subscribe({
      next: (planes) => {
        this.planes.set(planes);
        this.cargando.set(false);
      },
      error: (error: unknown) => {
        this.cargando.set(false);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  /** Precio en pesos colombianos, exacto: se formatea la cadena que devolvió
   * el backend sin convertirla a `number`, así que no hay redondeo posible. */
  protected precioFormateado(plan: Plan): string {
    return `$ ${formatearMonto(plan.precio)}`;
  }

  /** Eco de lo que se va a guardar, bajo el campo de precio. Hace visible la
   * interpretación de lo tecleado ("5.000" son cinco mil pesos, no cinco)
   * antes de enviarlo, en vez de dejarla a la adivinanza. */
  protected precioInterpretado(): string | null {
    const normalizado = normalizarPrecio(this.form.controls.precio.value);
    return normalizado === null ? null : `$ ${formatearMonto(normalizado)}`;
  }

  protected etiquetaTipo(tipo: TipoPlan): string {
    return ETIQUETAS_TIPO_PLAN[tipo] ?? tipo;
  }

  /** Icono del plan según su tipo: hace la fila reconocible de un vistazo
   * sin tener que leer la columna de duración. Los de vigencia usan
   * calendario (mes / quincena); el de sesión, un rayo, porque no cuenta
   * días sino accesos sueltos. */
  protected iconoTipo(tipo: TipoPlan): string {
    switch (tipo) {
      case 'mensual':
        return 'calendar_month';
      case 'quincenal':
        return 'date_range';
      default:
        return 'bolt';
    }
  }

  protected nombreSede(sedeId: number | null): string {
    if (sedeId === null) {
      return 'Todas las sedes';
    }
    return this.sedes().find((s) => s.id === sedeId)?.nombre ?? `Sede #${sedeId}`;
  }

  protected abrirCreacion(): void {
    this.planEditando.set(null);
    this.erroresCampo.set({});
    this.form.reset({
      nombre: '',
      precio: '',
      tipo: 'mensual',
      duracion_dias: 30,
      sede: '',
      requiere_entrenador: false,
      activo: true,
    });
    this.panelAbierto.set(true);
  }

  protected abrirEdicion(plan: Plan): void {
    this.planEditando.set(plan);
    this.erroresCampo.set({});
    this.form.reset({
      nombre: plan.nombre,
      // Se edita en el formato que el usuario lee ("49.990"), no en el
      // canónico del backend ("49990.00"); `normalizarPrecio` lo devuelve a
      // su forma al guardar, sin alterar el importe.
      precio: formatearMonto(plan.precio),
      tipo: plan.tipo,
      duracion_dias: plan.duracion_dias,
      sede: plan.sede ?? '',
      requiere_entrenador: plan.requiere_entrenador,
      activo: plan.activo,
    });
    this.panelAbierto.set(true);
  }

  protected cerrarPanel(): void {
    this.panelAbierto.set(false);
    this.erroresCampo.set({});
  }

  protected errorDe(campo: string): string | null {
    const valor = this.erroresCampo()[campo];
    if (!valor) {
      return null;
    }
    return Array.isArray(valor) ? valor[0] : valor;
  }

  protected enviar(): void {
    if (this.guardando()) {
      return;
    }

    this.form.markAllAsTouched();
    if (this.form.invalid) {
      return;
    }

    this.erroresCampo.set({});
    this.guardando.set(true);

    const valores = this.form.getRawValue();
    // `precioValido` ya garantizó que normaliza; el `?? ''` es solo para
    // satisfacer al compilador, no un caso alcanzable.
    const datos: PlanFormulario = {
      nombre: valores.nombre.trim(),
      precio: normalizarPrecio(valores.precio) ?? '',
      tipo: valores.tipo,
      duracion_dias: valores.tipo === 'por_sesion' ? null : valores.duracion_dias,
      sede: valores.sede === '' ? null : valores.sede,
      requiere_entrenador: valores.requiere_entrenador,
      activo: valores.activo,
    };

    const planEditando = this.planEditando();
    const peticion$ = planEditando
      ? this.planesService.actualizar(planEditando.id, datos)
      : this.planesService.crear(datos);

    peticion$.subscribe({
      next: () => {
        this.guardando.set(false);
        this.cerrarPanel();
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        this.manejarError(error);
      },
    });
  }

  protected darDeBaja(plan: Plan): void {
    if (this.eliminandoId() !== null) {
      return;
    }
    const confirmado = confirm(
      `¿Dar de baja el plan "${plan.nombre}"? Dejará de estar disponible para la venta; ` +
        'las membresías ya vendidas no se ven afectadas.',
    );
    if (!confirmado) {
      return;
    }

    this.eliminandoId.set(plan.id);
    this.planesService.eliminar(plan.id).subscribe({
      next: () => {
        this.eliminandoId.set(null);
        if (this.planEditando()?.id === plan.id) {
          this.cerrarPanel();
        }
        this.cargar();
      },
      error: (error: unknown) => {
        this.eliminandoId.set(null);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  /**
   * Devuelve un plan dado de baja al catálogo.
   *
   * Técnicamente ya se podía: abrir "Editar" y marcar la casilla "Plan
   * activo". Pero en la fila de un plan inactivo el único botón visible era
   * "Dar de baja" —que ya no hacía nada—, así que la única salida estaba
   * escondida dentro de un formulario y la pantalla daba a entender que la
   * baja era definitiva.
   *
   * Sin confirmación: reactivar no destruye nada y se deshace dándolo de
   * baja otra vez.
   */
  protected reactivar(plan: Plan): void {
    if (this.eliminandoId() !== null) {
      return;
    }
    this.eliminandoId.set(plan.id);
    this.error.set(null);
    this.planesService.actualizar(plan.id, { activo: true }).subscribe({
      next: () => {
        this.eliminandoId.set(null);
        this.cargar();
      },
      error: (error: unknown) => {
        this.eliminandoId.set(null);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  private manejarError(error: unknown): void {
    if (error instanceof HttpErrorResponse && error.status === 400 && error.error) {
      const cuerpo = error.error as Record<string, unknown>;
      if (cuerpo['detail']) {
        this.error.set(String(cuerpo['detail']));
        return;
      }
      // Diccionario de errores por campo (p. ej. nombre duplicado): se
      // muestran tal cual, en español, debajo de cada campo.
      this.erroresCampo.set(cuerpo as ErroresDeCampo);
      return;
    }
    this.error.set(this.mensajeDeError(error));
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo completar la operación. Inténtalo de nuevo.';
  }
}
