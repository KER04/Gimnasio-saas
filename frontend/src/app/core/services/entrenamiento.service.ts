import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import {
  Comparativa,
  ControlMedida,
  Ejercicio,
  EjercicioFormulario,
  FichaFormulario,
  FichaMedidas,
  GrupoMuscular,
  Rutina,
  RutinaFormulario,
} from '../models/entrenamiento.model';

/**
 * Entrenamiento (RF-12).
 *
 * El catálogo y las rutinas exigen `rutinas.gestionar`; las fichas de
 * medidas, `medidas.gestionar`. El rol `entrenador` trae los dos.
 */
@Injectable({ providedIn: 'root' })
export class EntrenamientoService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiUrl;

  // --- Catálogo ---

  listarGrupos(): Observable<GrupoMuscular[]> {
    return this.http
      .get<RespuestaPaginada<GrupoMuscular>>(`${this.base}/grupos-musculares/`)
      .pipe(map((r) => r.results));
  }

  /** Con `incluirInactivos` salen también los dados de baja, que es la única
   * forma de poder reactivarlos. */
  listarEjercicios(incluirInactivos = false, grupo?: number): Observable<Ejercicio[]> {
    let params = new HttpParams();
    if (incluirInactivos) {
      params = params.set('incluir_inactivos', '1');
    }
    if (grupo !== undefined) {
      params = params.set('grupo', String(grupo));
    }
    return this.http
      .get<RespuestaPaginada<Ejercicio>>(`${this.base}/ejercicios/`, { params })
      .pipe(map((r) => r.results));
  }

  crearEjercicio(datos: EjercicioFormulario): Observable<Ejercicio> {
    return this.http.post<Ejercicio>(`${this.base}/ejercicios/`, datos);
  }

  actualizarEjercicio(id: number, datos: Partial<EjercicioFormulario>): Observable<Ejercicio> {
    return this.http.patch<Ejercicio>(`${this.base}/ejercicios/${id}/`, datos);
  }

  /** Baja LÓGICA: `RutinaEjercicio.ejercicio` es PROTECT. */
  darDeBajaEjercicio(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/ejercicios/${id}/`);
  }

  // --- Rutinas ---

  listarRutinas(cliente?: number, incluirArchivadas = false): Observable<Rutina[]> {
    let params = new HttpParams();
    if (cliente !== undefined) {
      params = params.set('cliente', String(cliente));
    }
    if (incluirArchivadas) {
      params = params.set('incluir_inactivas', '1');
    }
    return this.http
      .get<RespuestaPaginada<Rutina>>(`${this.base}/rutinas/`, { params })
      .pipe(map((r) => r.results));
  }

  obtenerRutina(id: number): Observable<Rutina> {
    return this.http.get<Rutina>(`${this.base}/rutinas/${id}/`);
  }

  /** La rutina va ENTERA, con sus días y ejercicios, en una sola petición. */
  crearRutina(datos: RutinaFormulario): Observable<Rutina> {
    return this.http.post<Rutina>(`${this.base}/rutinas/`, datos);
  }

  /** Si se mandan `dias`, SUSTITUYEN a los que había. Omitirlos los deja
   * intactos, que es lo que se quiere al cambiar solo el objetivo. */
  actualizarRutina(id: number, datos: Partial<RutinaFormulario>): Observable<Rutina> {
    return this.http.patch<Rutina>(`${this.base}/rutinas/${id}/`, datos);
  }

  /** Archiva, no borra: es el histórico de lo que ese cliente entrenó. */
  archivarRutina(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/rutinas/${id}/`);
  }

  // --- Medidas ---

  listarFichas(cliente?: number, incluirCerradas = false): Observable<FichaMedidas[]> {
    let params = new HttpParams();
    if (cliente !== undefined) {
      params = params.set('cliente', String(cliente));
    }
    if (incluirCerradas) {
      params = params.set('incluir_inactivos', '1');
    }
    return this.http
      .get<RespuestaPaginada<FichaMedidas>>(`${this.base}/fichas-medidas/`, { params })
      .pipe(map((r) => r.results));
  }

  /** Falla con 400 si el cliente ya tiene un proceso abierto: solo puede
   * haber uno a la vez. */
  abrirFicha(datos: FichaFormulario): Observable<FichaMedidas> {
    return this.http.post<FichaMedidas>(`${this.base}/fichas-medidas/`, datos);
  }

  cerrarFicha(id: number): Observable<FichaMedidas> {
    return this.http.post<FichaMedidas>(`${this.base}/fichas-medidas/${id}/cerrar/`, {});
  }

  /** El `numero_control` lo pone el servidor: es el siguiente de la ficha. */
  registrarControl(fichaId: number, medidas: Record<string, unknown>): Observable<ControlMedida> {
    return this.http.post<ControlMedida>(
      `${this.base}/fichas-medidas/${fichaId}/controles/`, medidas,
    );
  }

  /** Cada medida con su valor en cada control y la diferencia. Es la vista
   * para la que existe la tabla. */
  comparativa(fichaId: number): Observable<Comparativa> {
    return this.http.get<Comparativa>(`${this.base}/fichas-medidas/${fichaId}/comparativa/`);
  }
}
