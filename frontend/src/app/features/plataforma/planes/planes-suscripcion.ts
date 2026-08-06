import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { PlataformaService } from '../../../core/services/plataforma.service';
import { PlanSuscripcion } from '../../../core/models/plataforma.model';
import { normalizarPrecio, precioParaMostrar, precioValido } from '../../../core/utils/precio.util';

type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Catálogo de planes de suscripción: lo que le vendes a los gimnasios.
 *
 * El precio es POR SEDE (decisión 13 del esquema), así que la pantalla lo
 * dice en todas partes: un plan de 80.000 le cuesta 240.000 a un gimnasio
 * con tres sedes, y confundirlo al fijar precios sale caro.
 */
@Component({
  selector: 'app-plataforma-planes',
  imports: [ReactiveFormsModule],
  templateUrl: './planes-suscripcion.html',
})
export class PlataformaPlanes {
  private readonly plataformaService = inject(PlataformaService);
  private readonly fb = inject(FormBuilder);

  protected readonly puedeGestionar = this.plataformaService.esAdministrador;

  protected readonly planes = signal<PlanSuscripcion[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly panelAbierto = signal(false);
  protected readonly planEditando = signal<PlanSuscripcion | null>(null);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', [Validators.required]],
    // Texto y no `number`: el dinero se trata como cadena en todo el
    // proyecto, y un input numérico cambia el valor con la rueda del ratón.
    precio_por_sede: ['', [Validators.required, precioValido]],
    ciclo: this.fb.nonNullable.control<'mensual' | 'anual'>('mensual'),
    // Vacío = sin límite. Es distinto de cero, que el backend rechaza.
    max_sedes: [''],
    max_usuarios: [''],
    max_clientes_activos: [''],
    activo: [true],
  });

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    // Se piden TAMBIÉN los dados de baja: es el único sitio desde el que se
    // pueden reactivar. Si solo se vieran los activos, dar de baja un plan
    // sería un viaje sin retorno.
    this.plataformaService.listarPlanes(true).subscribe({
      next: (planes) => {
        this.planes.set(planes);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar los planes.');
      },
    });
  }

  protected abrirAlta(): void {
    this.planEditando.set(null);
    this.erroresCampo.set({});
    this.formulario.reset({ ciclo: 'mensual', activo: true });
    this.panelAbierto.set(true);
  }

  protected abrirEdicion(plan: PlanSuscripcion): void {
    this.planEditando.set(plan);
    this.erroresCampo.set({});
    this.formulario.reset({
      nombre: plan.nombre,
      precio_por_sede: precioParaMostrar(plan.precio_por_sede),
      ciclo: plan.ciclo,
      max_sedes: plan.max_sedes === null ? '' : String(plan.max_sedes),
      max_usuarios: plan.max_usuarios === null ? '' : String(plan.max_usuarios),
      max_clientes_activos:
        plan.max_clientes_activos === null ? '' : String(plan.max_clientes_activos),
      activo: plan.activo,
    });
    this.panelAbierto.set(true);
  }

  protected cerrarPanel(): void {
    this.panelAbierto.set(false);
    this.planEditando.set(null);
    this.erroresCampo.set({});
  }

  /** `''` -> `null` (sin límite). El backend rechaza el cero, que sería un
   * plan donde no cabe nada. */
  private limite(valor: string): number | null {
    const limpio = valor.trim();
    return limpio === '' ? null : Number(limpio);
  }

  protected guardar(): void {
    if (this.guardando()) {
      return;
    }
    this.formulario.markAllAsTouched();
    if (this.formulario.invalid) {
      return;
    }

    this.guardando.set(true);
    this.erroresCampo.set({});

    const v = this.formulario.getRawValue();
    const datos = {
      nombre: v.nombre.trim(),
      precio_por_sede: normalizarPrecio(v.precio_por_sede) ?? '0',
      ciclo: v.ciclo,
      max_sedes: this.limite(v.max_sedes),
      max_usuarios: this.limite(v.max_usuarios),
      max_clientes_activos: this.limite(v.max_clientes_activos),
      activo: v.activo,
    };

    const editando = this.planEditando();
    const peticion$ = editando
      ? this.plataformaService.actualizarPlan(editando.id, datos)
      : this.plataformaService.crearPlan(datos);

    peticion$.subscribe({
      next: () => {
        this.guardando.set(false);
        this.cerrarPanel();
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
          this.erroresCampo.set(error.error as ErroresDeCampo);
        } else {
          this.error.set('No se pudo guardar el plan.');
        }
      },
    });
  }

  protected darDeBaja(plan: PlanSuscripcion): void {
    if (!confirm(`¿Dar de baja el plan "${plan.nombre}"? Dejará de poder contratarse. Los gimnasios que ya lo tengan siguen igual.`)) {
      return;
    }
    this.error.set(null);
    this.plataformaService.darDeBajaPlan(plan.id).subscribe({
      next: () => this.cargar(),
      error: () => this.error.set('No se pudo dar de baja el plan.'),
    });
  }

  protected reactivar(plan: PlanSuscripcion): void {
    this.error.set(null);
    this.plataformaService.actualizarPlan(plan.id, { activo: true }).subscribe({
      next: () => this.cargar(),
      error: () => this.error.set('No se pudo reactivar el plan.'),
    });
  }

  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  protected dinero(valor: string): string {
    return precioParaMostrar(valor);
  }

  protected limiteTexto(valor: number | null): string {
    return valor === null ? 'Sin límite' : valor.toLocaleString('es-CO');
  }
}
