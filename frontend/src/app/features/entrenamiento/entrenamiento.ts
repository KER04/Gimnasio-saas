import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { ClientesService } from '../../core/services/clientes.service';
import { EntrenamientoService } from '../../core/services/entrenamiento.service';
import { ClienteResumen } from '../../core/models/cliente.model';
import {
  Ejercicio,
  GrupoMuscular,
  Rutina,
  RutinaDia,
  RutinaEjercicio,
} from '../../core/models/entrenamiento.model';

type ErroresDeCampo = Record<string, string | string[]>;
type Pestana = 'rutinas' | 'ejercicios';

/**
 * Entrenamiento: el catálogo de ejercicios del gimnasio y las rutinas que se
 * arman con él.
 *
 * Una rutina se guarda ENTERA en una petición, con sus días y sus ejercicios:
 * es un documento que el entrenador compone de una vez. Por eso todo el
 * armado vive en memoria hasta que se pulsa guardar.
 */
@Component({
  selector: 'app-entrenamiento',
  imports: [ReactiveFormsModule],
  templateUrl: './entrenamiento.html',
})
export class Entrenamiento {
  private readonly servicio = inject(EntrenamientoService);
  private readonly clientesService = inject(ClientesService);
  private readonly fb = inject(FormBuilder);

  protected readonly pestana = signal<Pestana>('rutinas');

  protected readonly ejercicios = signal<Ejercicio[]>([]);
  protected readonly grupos = signal<GrupoMuscular[]>([]);
  protected readonly rutinas = signal<Rutina[]>([]);
  protected readonly clientes = signal<ClienteResumen[]>([]);

  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly verInactivos = signal(false);

  // --- Catálogo ---
  protected readonly panelEjercicio = signal(false);
  protected readonly ejercicioEditando = signal<Ejercicio | null>(null);
  protected readonly guardandoEjercicio = signal(false);
  protected readonly erroresEjercicio = signal<ErroresDeCampo>({});

  protected readonly formEjercicio = this.fb.nonNullable.group({
    nombre: ['', [Validators.required]],
    grupo_muscular: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    descripcion: [''],
  });

  /** Ejercicios activos agrupados por grupo muscular, para el catálogo y
   * para el selector al armar una rutina. */
  protected readonly porGrupo = computed(() => {
    const grupos = this.grupos();
    return grupos
      .map((g) => ({
        grupo: g,
        ejercicios: this.ejercicios().filter((e) => e.grupo_muscular === g.id),
      }))
      .filter((bloque) => bloque.ejercicios.length > 0);
  });

  protected readonly ejerciciosActivos = computed(() =>
    this.ejercicios().filter((e) => e.activo),
  );

  // --- Rutinas ---
  protected readonly panelRutina = signal(false);
  protected readonly rutinaEditando = signal<Rutina | null>(null);
  protected readonly guardandoRutina = signal(false);
  protected readonly erroresRutina = signal<ErroresDeCampo>({});
  protected readonly ocupadoId = signal<number | null>(null);
  protected readonly rutinaAbierta = signal<number | null>(null);

  protected readonly formRutina = this.fb.nonNullable.group({
    cliente: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    nombre: ['', [Validators.required]],
    objetivo: [''],
    fecha_fin: [''],
  });

  /** Los días en construcción. Viven aquí y no en el formulario porque son
   * una estructura anidada que se manipula entera. */
  protected readonly dias = signal<RutinaDia[]>([]);

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    forkJoin({
      ejercicios: this.servicio.listarEjercicios(true),
      grupos: this.servicio.listarGrupos(),
      rutinas: this.servicio.listarRutinas(undefined, this.verInactivos()),
      clientes: this.clientesService.listar(),
    }).subscribe({
      next: ({ ejercicios, grupos, rutinas, clientes }) => {
        this.ejercicios.set(ejercicios);
        this.grupos.set(grupos);
        this.rutinas.set(rutinas);
        this.clientes.set(clientes.results);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudo cargar el módulo de entrenamiento.');
      },
    });
  }

  protected cambiarPestana(valor: Pestana): void {
    this.pestana.set(valor);
    this.panelEjercicio.set(false);
    this.panelRutina.set(false);
  }

  protected alternarInactivos(): void {
    this.verInactivos.update((v) => !v);
    this.cargar();
  }

  // --- Catálogo de ejercicios ------------------------------------------

  protected abrirAltaEjercicio(): void {
    this.ejercicioEditando.set(null);
    this.erroresEjercicio.set({});
    this.formEjercicio.reset({ grupo_muscular: '' });
    this.panelEjercicio.set(true);
  }

  protected abrirEdicionEjercicio(ejercicio: Ejercicio): void {
    this.ejercicioEditando.set(ejercicio);
    this.erroresEjercicio.set({});
    this.formEjercicio.reset({
      nombre: ejercicio.nombre,
      grupo_muscular: ejercicio.grupo_muscular,
      descripcion: ejercicio.descripcion ?? '',
    });
    this.panelEjercicio.set(true);
  }

  protected guardarEjercicio(): void {
    if (this.guardandoEjercicio()) {
      return;
    }
    this.formEjercicio.markAllAsTouched();
    if (this.formEjercicio.invalid) {
      return;
    }

    this.guardandoEjercicio.set(true);
    this.erroresEjercicio.set({});

    const v = this.formEjercicio.getRawValue();
    const datos = {
      nombre: v.nombre.trim(),
      grupo_muscular: v.grupo_muscular as number,
      descripcion: v.descripcion.trim() || null,
    };

    const editando = this.ejercicioEditando();
    const peticion$ = editando
      ? this.servicio.actualizarEjercicio(editando.id, datos)
      : this.servicio.crearEjercicio(datos);

    peticion$.subscribe({
      next: () => {
        this.guardandoEjercicio.set(false);
        this.panelEjercicio.set(false);
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardandoEjercicio.set(false);
        if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
          this.erroresEjercicio.set(error.error as ErroresDeCampo);
        } else {
          this.error.set('No se pudo guardar el ejercicio.');
        }
      },
    });
  }

  protected darDeBajaEjercicio(ejercicio: Ejercicio): void {
    if (!confirm(`¿Dar de baja "${ejercicio.nombre}"? No podrá añadirse a rutinas nuevas. Las rutinas que ya lo usan no cambian.`)) {
      return;
    }
    this.ocupadoId.set(ejercicio.id);
    this.servicio.darDeBajaEjercicio(ejercicio.id).subscribe({
      next: () => {
        this.ocupadoId.set(null);
        this.cargar();
      },
      error: () => {
        this.ocupadoId.set(null);
        this.error.set('No se pudo dar de baja el ejercicio.');
      },
    });
  }

  protected reactivarEjercicio(ejercicio: Ejercicio): void {
    this.ocupadoId.set(ejercicio.id);
    this.servicio.actualizarEjercicio(ejercicio.id, { activo: true }).subscribe({
      next: () => {
        this.ocupadoId.set(null);
        this.cargar();
      },
      error: () => {
        this.ocupadoId.set(null);
        this.error.set('No se pudo reactivar el ejercicio.');
      },
    });
  }

  // --- Rutinas ---------------------------------------------------------

  protected abrirAltaRutina(): void {
    this.rutinaEditando.set(null);
    this.erroresRutina.set({});
    this.formRutina.reset({ cliente: '' });
    // Una rutina empieza con un día: crear una vacía y tener que pulsar
    // "añadir día" antes de poder hacer nada es un paso de más.
    this.dias.set([{ numero: 1, nombre: 'Día 1', ejercicios: [] }]);
    this.panelRutina.set(true);
  }

  protected abrirEdicionRutina(rutina: Rutina): void {
    this.rutinaEditando.set(rutina);
    this.erroresRutina.set({});
    this.formRutina.reset({
      cliente: rutina.cliente,
      nombre: rutina.nombre,
      objetivo: rutina.objetivo ?? '',
      fecha_fin: rutina.fecha_fin ?? '',
    });
    // Copia profunda: se edita en memoria y solo se manda al guardar, así
    // cancelar no deja la rutina a medias.
    this.dias.set(
      rutina.dias.map((d) => ({
        numero: d.numero,
        nombre: d.nombre,
        ejercicios: d.ejercicios.map((e) => ({ ...e })),
      })),
    );
    this.panelRutina.set(true);
  }

  protected cerrarPanelRutina(): void {
    this.panelRutina.set(false);
    this.rutinaEditando.set(null);
    this.dias.set([]);
    this.erroresRutina.set({});
  }

  protected agregarDia(): void {
    this.dias.update((dias) => {
      const numero = dias.length === 0 ? 1 : Math.max(...dias.map((d) => d.numero)) + 1;
      return [...dias, { numero, nombre: `Día ${numero}`, ejercicios: [] }];
    });
  }

  protected quitarDia(indice: number): void {
    this.dias.update((dias) => dias.filter((_, i) => i !== indice));
  }

  protected renombrarDia(indice: number, nombre: string): void {
    this.dias.update((dias) =>
      dias.map((d, i) => (i === indice ? { ...d, nombre } : d)),
    );
  }

  protected agregarEjercicio(indiceDia: number, ejercicioId: number): void {
    if (!ejercicioId) {
      return;
    }
    this.dias.update((dias) =>
      dias.map((dia, i) => {
        if (i !== indiceDia) {
          return dia;
        }
        const orden =
          dia.ejercicios.length === 0
            ? 1
            : Math.max(...dia.ejercicios.map((e) => e.orden)) + 1;
        const catalogo = this.ejercicios().find((e) => e.id === ejercicioId);
        return {
          ...dia,
          ejercicios: [
            ...dia.ejercicios,
            {
              ejercicio: ejercicioId,
              ejercicio_nombre: catalogo?.nombre,
              grupo_nombre: catalogo?.grupo_nombre,
              orden,
              series: 3,
              repeticiones: 10,
              peso_kg: null,
              descanso_segundos: null,
              notas: null,
            },
          ],
        };
      }),
    );
  }

  protected quitarEjercicio(indiceDia: number, indiceEjercicio: number): void {
    this.dias.update((dias) =>
      dias.map((dia, i) =>
        i !== indiceDia
          ? dia
          : {
              ...dia,
              // Se renumera el orden: la base exige que sea único dentro del
              // día, y dejar huecos tras borrar el del medio invita a chocar.
              ejercicios: dia.ejercicios
                .filter((_, j) => j !== indiceEjercicio)
                .map((e, j) => ({ ...e, orden: j + 1 })),
            },
      ),
    );
  }

  protected moverEjercicio(indiceDia: number, indiceEjercicio: number, delta: number): void {
    this.dias.update((dias) =>
      dias.map((dia, i) => {
        if (i !== indiceDia) {
          return dia;
        }
        const lista = [...dia.ejercicios];
        const destino = indiceEjercicio + delta;
        if (destino < 0 || destino >= lista.length) {
          return dia;
        }
        [lista[indiceEjercicio], lista[destino]] = [lista[destino], lista[indiceEjercicio]];
        return { ...dia, ejercicios: lista.map((e, j) => ({ ...e, orden: j + 1 })) };
      }),
    );
  }

  protected cambiarCampo(
    indiceDia: number,
    indiceEjercicio: number,
    campo: 'series' | 'repeticiones' | 'peso_kg' | 'descanso_segundos',
    valor: string,
  ): void {
    this.dias.update((dias) =>
      dias.map((dia, i) =>
        i !== indiceDia
          ? dia
          : {
              ...dia,
              ejercicios: dia.ejercicios.map((e, j) => {
                if (j !== indiceEjercicio) {
                  return e;
                }
                if (campo === 'peso_kg') {
                  return { ...e, peso_kg: valor.trim() || null };
                }
                const numero = Number(valor);
                if (campo === 'descanso_segundos') {
                  return { ...e, descanso_segundos: valor.trim() === '' ? null : numero };
                }
                return { ...e, [campo]: numero };
              }),
            },
      ),
    );
  }

  protected guardarRutina(): void {
    if (this.guardandoRutina()) {
      return;
    }
    this.formRutina.markAllAsTouched();
    if (this.formRutina.invalid) {
      return;
    }

    this.guardandoRutina.set(true);
    this.erroresRutina.set({});

    const v = this.formRutina.getRawValue();
    const datos = {
      cliente: v.cliente as number,
      nombre: v.nombre.trim(),
      objetivo: v.objetivo.trim() || null,
      fecha_fin: v.fecha_fin || null,
      dias: this.dias(),
    };

    const editando = this.rutinaEditando();
    const peticion$ = editando
      ? this.servicio.actualizarRutina(editando.id, datos)
      : this.servicio.crearRutina(datos);

    peticion$.subscribe({
      next: () => {
        this.guardandoRutina.set(false);
        this.cerrarPanelRutina();
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardandoRutina.set(false);
        if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
          this.erroresRutina.set(error.error as ErroresDeCampo);
        } else {
          this.error.set('No se pudo guardar la rutina.');
        }
      },
    });
  }

  protected archivar(rutina: Rutina): void {
    if (!confirm(`¿Archivar la rutina "${rutina.nombre}"? Se conserva como histórico de lo que ese cliente entrenó.`)) {
      return;
    }
    this.ocupadoId.set(rutina.id);
    this.servicio.archivarRutina(rutina.id).subscribe({
      next: () => {
        this.ocupadoId.set(null);
        this.cargar();
      },
      error: () => {
        this.ocupadoId.set(null);
        this.error.set('No se pudo archivar la rutina.');
      },
    });
  }

  protected alternarDetalle(rutina: Rutina): void {
    this.rutinaAbierta.update((abierta) => (abierta === rutina.id ? null : rutina.id));
  }

  // --- Presentación ----------------------------------------------------

  protected erroresDeEjercicio(campo: string): string[] {
    const valor = this.erroresEjercicio()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  protected erroresDeRutina(campo: string): string[] {
    const valor = this.erroresRutina()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  /** Errores de la estructura anidada: el backend los devuelve bajo `dias` y
   * no encajan en ningún campo del formulario. */
  protected errorDeDias(): string | null {
    const valor = this.erroresRutina()['dias'];
    if (valor === undefined) {
      return null;
    }
    return Array.isArray(valor) ? String(valor[0]) : String(valor);
  }

  protected totalEjercicios(rutina: Rutina): number {
    return rutina.dias.reduce((suma, d) => suma + d.ejercicios.length, 0);
  }

  protected fecha(valor: string | null): string {
    if (!valor) {
      return '—';
    }
    const fecha = new Date(`${valor}T00:00:00`);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  protected descanso(segundos: number | null): string {
    if (segundos === null) {
      return '—';
    }
    if (segundos < 60) {
      return `${segundos} s`;
    }
    const minutos = Math.floor(segundos / 60);
    const resto = segundos % 60;
    return resto === 0 ? `${minutos} min` : `${minutos} min ${resto} s`;
  }
}
