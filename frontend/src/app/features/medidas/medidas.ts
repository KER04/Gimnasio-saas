import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { ClientesService } from '../../core/services/clientes.service';
import { EntrenamientoService } from '../../core/services/entrenamiento.service';
import { ClienteResumen } from '../../core/models/cliente.model';
import {
  Comparativa,
  ETIQUETAS_MEDIDA,
  FichaMedidas,
  MEDIDAS,
  Medida,
} from '../../core/models/entrenamiento.model';

type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Seguimiento corporal (RF-12).
 *
 * Pantalla aparte de Entrenamiento a propósito: su permiso es
 * `medidas.gestionar`, distinto de `rutinas.gestionar`. Alguien puede tener
 * uno y no el otro, y meterlas juntas obligaría a exigir los dos.
 *
 * Un cliente tiene como mucho un proceso abierto a la vez. La vista que
 * importa es la comparativa: ver si el abdomen bajó, no releer 13 números
 * sueltos por control.
 */
@Component({
  selector: 'app-medidas',
  imports: [ReactiveFormsModule],
  templateUrl: './medidas.html',
})
export class Medidas {
  private readonly servicio = inject(EntrenamientoService);
  private readonly clientesService = inject(ClientesService);
  private readonly fb = inject(FormBuilder);

  protected readonly medidas = MEDIDAS;
  protected readonly etiquetas = ETIQUETAS_MEDIDA;

  protected readonly fichas = signal<FichaMedidas[]>([]);
  protected readonly clientes = signal<ClienteResumen[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly verCerradas = signal(false);

  protected readonly fichaAbierta = signal<FichaMedidas | null>(null);
  protected readonly comparativa = signal<Comparativa | null>(null);
  protected readonly cargandoComparativa = signal(false);

  protected readonly panelFicha = signal(false);
  protected readonly panelControl = signal(false);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly formFicha = this.fb.nonNullable.group({
    cliente: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    estatura_cm: [''],
    modalidad: [''],
    whatsapp: [''],
  });

  /** Un control: las 13 medidas más la edad. Todas opcionales — en la
   * práctica no siempre se toman todas, y exigirlas haría que no se
   * registrara ninguna. */
  protected readonly formControl = this.fb.nonNullable.group({
    fecha: [''],
    edad: [''],
    peso_kg: [''],
    cuello: [''],
    hombros: [''],
    pecho_espalda: [''],
    brazos: [''],
    antebrazos: [''],
    muneca: [''],
    abdomen: [''],
    cintura: [''],
    cadera_gluteos: [''],
    piernas_media: [''],
    rodillas_arriba: [''],
    pantorrillas: [''],
    tobillos: [''],
  });

  /** Clientes que aún no tienen proceso abierto: ofrecer los que ya lo tienen
   * solo llevaría a un error del servidor. */
  protected readonly clientesDisponibles = computed(() => {
    const conFichaAbierta = new Set(
      this.fichas().filter((f) => f.activa).map((f) => f.cliente),
    );
    return this.clientes().filter((c) => !conFichaAbierta.has(c.id));
  });

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    forkJoin({
      fichas: this.servicio.listarFichas(undefined, this.verCerradas()),
      clientes: this.clientesService.listar(),
    }).subscribe({
      next: ({ fichas, clientes }) => {
        this.fichas.set(fichas);
        this.clientes.set(clientes.results);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar las fichas.');
      },
    });
  }

  protected alternarCerradas(): void {
    this.verCerradas.update((v) => !v);
    this.cargar();
  }

  // --- Ficha -----------------------------------------------------------

  protected abrirAltaFicha(): void {
    this.erroresCampo.set({});
    this.formFicha.reset({ cliente: '' });
    this.panelFicha.set(true);
  }

  protected crearFicha(): void {
    if (this.guardando()) {
      return;
    }
    this.formFicha.markAllAsTouched();
    if (this.formFicha.invalid) {
      return;
    }

    this.guardando.set(true);
    this.erroresCampo.set({});

    const v = this.formFicha.getRawValue();
    this.servicio
      .abrirFicha({
        cliente: v.cliente as number,
        estatura_cm: v.estatura_cm.trim() || null,
        modalidad: v.modalidad.trim() || null,
        whatsapp: v.whatsapp.trim() || null,
      })
      .subscribe({
        next: (ficha) => {
          this.guardando.set(false);
          this.panelFicha.set(false);
          this.cargar();
          this.seleccionar(ficha);
        },
        error: (error: unknown) => {
          this.guardando.set(false);
          this.procesarError(error, 'No se pudo abrir la ficha.');
        },
      });
  }

  protected seleccionar(ficha: FichaMedidas): void {
    this.fichaAbierta.set(ficha);
    this.panelControl.set(false);
    this.cargarComparativa(ficha.id);
  }

  protected cerrarDetalle(): void {
    this.fichaAbierta.set(null);
    this.comparativa.set(null);
  }

  private cargarComparativa(fichaId: number): void {
    this.cargandoComparativa.set(true);
    this.servicio.comparativa(fichaId).subscribe({
      next: (datos) => {
        this.comparativa.set(datos);
        this.cargandoComparativa.set(false);
      },
      error: () => {
        this.cargandoComparativa.set(false);
        this.error.set('No se pudo cargar la comparativa.');
      },
    });
  }

  protected cerrarProceso(ficha: FichaMedidas): void {
    if (!confirm(`¿Cerrar el proceso de ${ficha.cliente_nombre}? Los controles se conservan y podrá empezar uno nuevo.`)) {
      return;
    }
    this.servicio.cerrarFicha(ficha.id).subscribe({
      next: () => {
        this.cerrarDetalle();
        this.cargar();
      },
      error: () => this.error.set('No se pudo cerrar el proceso.'),
    });
  }

  // --- Control ---------------------------------------------------------

  protected abrirControl(): void {
    this.erroresCampo.set({});
    this.formControl.reset();
    this.panelControl.set(true);
  }

  protected guardarControl(): void {
    const ficha = this.fichaAbierta();
    if (ficha === null || this.guardando()) {
      return;
    }

    this.guardando.set(true);
    this.erroresCampo.set({});

    // Solo se mandan las medidas que se tomaron: `''` significa "no se midió",
    // que no es lo mismo que cero.
    const valores = this.formControl.getRawValue() as Record<string, string>;
    const cuerpo: Record<string, unknown> = {};
    for (const [campo, valor] of Object.entries(valores)) {
      const limpio = valor.trim();
      if (limpio !== '') {
        cuerpo[campo] = limpio;
      }
    }

    this.servicio.registrarControl(ficha.id, cuerpo).subscribe({
      next: () => {
        this.guardando.set(false);
        this.panelControl.set(false);
        this.cargarComparativa(ficha.id);
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        this.procesarError(error, 'No se pudo registrar el control.');
      },
    });
  }

  private procesarError(error: unknown, porDefecto: string): void {
    if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
      this.erroresCampo.set(error.error as ErroresDeCampo);
      return;
    }
    this.error.set(porDefecto);
  }

  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  // --- Presentación ----------------------------------------------------

  protected etiqueta(medida: Medida): string {
    return this.etiquetas[medida];
  }

  /**
   * Si la diferencia es una mejora depende de la medida: bajar de abdomen
   * suele buscarse, bajar de brazos rara vez. Como el objetivo lo pone cada
   * cliente y no lo sabemos, NO se pinta de verde ni de rojo: solo se marca
   * la dirección. Colorearlo sería felicitar o alarmar por algo que puede
   * ser justo lo contrario de lo que se buscaba.
   */
  protected flecha(diferencia: string | null): string {
    if (diferencia === null) {
      return '';
    }
    const numero = Number(diferencia);
    if (numero === 0) {
      return '=';
    }
    return numero > 0 ? '▲' : '▼';
  }

  protected diferenciaTexto(diferencia: string | null): string {
    if (diferencia === null) {
      return '—';
    }
    const numero = Number(diferencia);
    return numero > 0 ? `+${diferencia}` : diferencia;
  }

  protected fecha(valor: string): string {
    const fecha = new Date(`${valor}T00:00:00`);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }
}
