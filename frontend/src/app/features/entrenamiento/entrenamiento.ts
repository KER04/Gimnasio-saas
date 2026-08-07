import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { ClientesService } from '../../core/services/clientes.service';
import { EntrenamientoService } from '../../core/services/entrenamiento.service';
import { ClienteResumen } from '../../core/models/cliente.model';
import {
  FiltroEstado,
  FiltroEstadoControl,
} from '../../shared/filtro-estado/filtro-estado';
import { mensajesDeError } from '../../core/utils/errores.util';
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
  imports: [ReactiveFormsModule, FiltroEstadoControl],
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

  /** Se traen SIEMPRE todos, activos e inactivos, y se filtra en memoria: son
   * listas pequeñas y así cambiar de filtro es instantáneo en vez de un viaje
   * al servidor por cada clic. */
  protected readonly filtro = signal<FiltroEstado>('activos');

  private coincide(activo: boolean): boolean {
    const filtro = this.filtro();
    return filtro === 'todos' || (filtro === 'activos') === activo;
  }

  protected readonly ejerciciosVisibles = computed(() =>
    this.ejercicios().filter((e) => this.coincide(e.activo)),
  );

  protected readonly rutinasVisibles = computed(() =>
    this.rutinas().filter((r) => this.coincide(r.activa)),
  );

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

  /** Ejercicios agrupados por grupo muscular, respetando el filtro. */
  protected readonly porGrupo = computed(() => {
    const visibles = this.ejerciciosVisibles();
    return this.grupos()
      .map((g) => ({
        grupo: g,
        ejercicios: visibles.filter((e) => e.grupo_muscular === g.id),
      }))
      .filter((bloque) => bloque.ejercicios.length > 0);
  });

  /** Para el selector al armar una rutina: solo activos, y sin depender del
   * filtro de la pantalla — una rutina nueva no puede llevar un ejercicio
   * retirado por mucho que se estén mirando los inactivos. */
  protected readonly porGrupoParaRutina = computed(() =>
    this.grupos()
      .map((g) => ({
        grupo: g,
        ejercicios: this.ejerciciosActivos().filter((e) => e.grupo_muscular === g.id),
      }))
      .filter((bloque) => bloque.ejercicios.length > 0),
  );

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
      rutinas: this.servicio.listarRutinas(undefined, true),
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

  // --- Catálogo de ejercicios ------------------------------------------

  /**
   * Abre el formulario de ejercicio, cambiando a su pestaña si hace falta.
   *
   * Se puede llamar desde la pestaña de Rutinas: el catálogo vacío es un
   * callejón sin salida si la única forma de crear un ejercicio es haber
   * cambiado antes de pestaña.
   */
  protected abrirAltaEjercicio(): void {
    this.pestana.set('ejercicios');
    this.panelRutina.set(false);
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
        // Los de cardio arrancan por TIEMPO: nadie prescribe "10
        // repeticiones de correr", y así el entrenador no tiene que cambiar
        // el modo a mano en el caso más obvio.
        const porTiempo = catalogo?.grupo_nombre?.toLowerCase() === 'cardio';
        return {
          ...dia,
          ejercicios: [
            ...dia.ejercicios,
            {
              ejercicio: ejercicioId,
              ejercicio_nombre: catalogo?.nombre,
              grupo_nombre: catalogo?.grupo_nombre,
              orden,
              series: porTiempo ? 1 : 3,
              repeticiones: porTiempo ? null : 10,
              duracion_minutos: porTiempo ? 20 : null,
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

  /** Aplica un cambio a un ejercicio concreto sin tocar los demás. */
  private editarEjercicio(
    indiceDia: number,
    indiceEjercicio: number,
    cambio: (e: RutinaEjercicio) => RutinaEjercicio,
  ): void {
    this.dias.update((dias) =>
      dias.map((dia, i) =>
        i !== indiceDia
          ? dia
          : {
              ...dia,
              ejercicios: dia.ejercicios.map((e, j) => (j === indiceEjercicio ? cambio(e) : e)),
            },
      ),
    );
  }

  protected cambiarCampo(
    indiceDia: number,
    indiceEjercicio: number,
    campo: 'series' | 'repeticiones' | 'duracion_minutos' | 'peso_kg' | 'descanso',
    valor: string,
  ): void {
    const texto = valor.trim();
    this.editarEjercicio(indiceDia, indiceEjercicio, (e) => {
      if (campo === 'peso_kg') {
        return { ...e, peso_kg: texto || null };
      }
      if (campo === 'descanso') {
        // La pantalla trabaja en MINUTOS y la columna guarda segundos: nadie
        // prescribe "90 segundos", dice "minuto y medio". Se admiten
        // decimales por eso mismo.
        const minutos = Number(texto.replace(',', '.'));
        return {
          ...e,
          descanso_segundos:
            texto === '' || Number.isNaN(minutos) ? null : Math.round(minutos * 60),
        };
      }
      const numero = Number(texto);
      const limpio = texto === '' || Number.isNaN(numero) ? null : numero;
      return { ...e, [campo]: limpio };
    });
  }

  /**
   * Cambia entre medir por repeticiones y medir por tiempo.
   *
   * Se vacía SIEMPRE la otra medida: la base exige exactamente una
   * (`ck_rutejer_medida`), y dejar las dos rellenadas daría "10 repeticiones
   * durante 5 minutos", que no significa nada.
   */
  protected cambiarModo(indiceDia: number, indiceEjercicio: number, porTiempo: boolean): void {
    this.editarEjercicio(indiceDia, indiceEjercicio, (e) =>
      porTiempo
        ? { ...e, repeticiones: null, duracion_minutos: e.duracion_minutos ?? 20 }
        : { ...e, duracion_minutos: null, repeticiones: e.repeticiones ?? 10 },
    );
  }

  /** Los minutos que enseña la casilla de descanso, desde los segundos
   * guardados. Sin decimales cuando son exactos: "2" y no "2.0". */
  protected descansoEnMinutos(segundos: number | null): string {
    if (segundos === null) {
      return '';
    }
    const minutos = segundos / 60;
    return Number.isInteger(minutos) ? String(minutos) : minutos.toFixed(1);
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

  /**
   * Errores de la estructura anidada, ya legibles.
   *
   * El backend los devuelve reflejando la forma del cuerpo enviado: bajo
   * `dias`, dentro de `ejercicios`, dentro del campo. Antes se hacía
   * `String(valor[0])` sobre eso y salía `[object Object]`: el usuario sabía
   * que algo estaba mal, pero no qué ni dónde. Ahora sale
   * "Día 1 · Ejercicio 2 · series: Debe ser mayor que cero".
   */
  protected erroresDeDias(): string[] {
    const valor = this.erroresRutina()['dias'];
    return valor === undefined ? [] : mensajesDeError({ dias: valor });
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
    const minutos = segundos / 60;
    return Number.isInteger(minutos) ? `${minutos} min` : `${minutos.toFixed(1)} min`;
  }

  /** Cómo se lee la carga de un ejercicio: "4×8" o "20 min". */
  protected medida(ejercicio: RutinaEjercicio): string {
    if (ejercicio.duracion_minutos !== null) {
      const series = ejercicio.series > 1 ? `${ejercicio.series} × ` : '';
      return `${series}${ejercicio.duracion_minutos} min`;
    }
    return `${ejercicio.series} × ${ejercicio.repeticiones}`;
  }

  protected esPorTiempo(ejercicio: RutinaEjercicio): boolean {
    return ejercicio.duracion_minutos !== null;
  }
}
