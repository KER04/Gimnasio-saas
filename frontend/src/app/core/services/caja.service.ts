import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import {
  CategoriaGasto,
  CategoriaIngreso,
  Gasto,
  GastoFormulario,
  IngresoFormulario,
  IngresoOtro,
} from '../models/caja.model';

/** Gastos e ingresos varios. Todo exige el permiso `gastos.gestionar`. */
@Injectable({ providedIn: 'root' })
export class CajaService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiUrl;

  private rango(filtros: { desde?: string; hasta?: string; sede?: number }): HttpParams {
    let params = new HttpParams();
    if (filtros.desde) {
      params = params.set('desde', filtros.desde);
    }
    if (filtros.hasta) {
      params = params.set('hasta', filtros.hasta);
    }
    if (filtros.sede !== undefined) {
      params = params.set('sede_id', String(filtros.sede));
    }
    return params;
  }

  // --- Gastos ---

  listarGastos(filtros: { desde?: string; hasta?: string; sede?: number } = {}): Observable<Gasto[]> {
    return this.http
      .get<RespuestaPaginada<Gasto>>(`${this.base}/gastos/`, { params: this.rango(filtros) })
      .pipe(map((respuesta) => respuesta.results));
  }

  crearGasto(datos: GastoFormulario): Observable<Gasto> {
    return this.http.post<Gasto>(`${this.base}/gastos/`, datos);
  }

  actualizarGasto(id: number, datos: Partial<GastoFormulario>): Observable<Gasto> {
    return this.http.patch<Gasto>(`${this.base}/gastos/${id}/`, datos);
  }

  /** Borrado REAL, no lógico: la tabla no tiene estado "anulado". Queda
   * registrado en auditoría con el importe y la descripción que tenía. */
  eliminarGasto(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/gastos/${id}/`);
  }

  listarCategoriasGasto(): Observable<CategoriaGasto[]> {
    return this.http
      .get<RespuestaPaginada<CategoriaGasto>>(`${this.base}/categorias-gasto/`)
      .pipe(map((respuesta) => respuesta.results));
  }

  // --- Ingresos varios ---

  listarIngresos(
    filtros: { desde?: string; hasta?: string; sede?: number } = {},
  ): Observable<IngresoOtro[]> {
    return this.http
      .get<RespuestaPaginada<IngresoOtro>>(`${this.base}/ingresos/`, { params: this.rango(filtros) })
      .pipe(map((respuesta) => respuesta.results));
  }

  crearIngreso(datos: IngresoFormulario): Observable<IngresoOtro> {
    return this.http.post<IngresoOtro>(`${this.base}/ingresos/`, datos);
  }

  actualizarIngreso(id: number, datos: Partial<IngresoFormulario>): Observable<IngresoOtro> {
    return this.http.patch<IngresoOtro>(`${this.base}/ingresos/${id}/`, datos);
  }

  eliminarIngreso(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/ingresos/${id}/`);
  }

  listarCategoriasIngreso(): Observable<CategoriaIngreso[]> {
    return this.http
      .get<RespuestaPaginada<CategoriaIngreso>>(`${this.base}/categorias-ingreso/`)
      .pipe(map((respuesta) => respuesta.results));
  }
}
