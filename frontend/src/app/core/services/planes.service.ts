import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { Plan, PlanFormulario } from '../models/plan.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Catálogo de planes (`/api/planes/`, ahora CRUD completo -- antes solo
 * lectura). `listar()` sigue siendo el usado por el selector de "Plan" del
 * listado de clientes y por la selección de plan del alta (RF-03): NO se
 * toca su forma, esos dos consumidores dependen de ella tal cual.
 *
 * El endpoint viene paginado (`PageNumberPagination` global, `PAGE_SIZE=20`),
 * pero para estos usos hace falta el catálogo completo de una vez (un
 * selector, no un listado con paginación propia): se pide y se devuelve
 * directamente `results` de la primera página. En la práctica un gimnasio
 * tiene un puñado de planes, muy por debajo de 20; si algún día tuviera más,
 * habría que recorrer `next` aquí, no en cada componente que lo usa.
 */
@Injectable({ providedIn: 'root' })
export class PlanesService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/planes`;

  listar(): Observable<Plan[]> {
    return this.http
      .get<RespuestaPaginada<Plan>>(`${this.base}/`)
      .pipe(map((respuesta) => respuesta.results));
  }

  /** Igual que `listar()`, pero incluye los planes dados de baja: la
   * pantalla de gestión los necesita para poder reactivarlos, mientras que
   * los selectores del POS y del alta de clientes solo deben ofrecer los
   * activos (por eso no se tocó `listar()`). */
  listarTodos(): Observable<Plan[]> {
    return this.http
      .get<RespuestaPaginada<Plan>>(`${this.base}/`, { params: { incluir_inactivos: '1' } })
      .pipe(map((respuesta) => respuesta.results));
  }

  crear(datos: PlanFormulario): Observable<Plan> {
    return this.http.post<Plan>(`${this.base}/`, datos);
  }

  actualizar(id: number, datos: Partial<PlanFormulario>): Observable<Plan> {
    return this.http.patch<Plan>(`${this.base}/${id}/`, datos);
  }

  /** Borrado LÓGICO (`activo=false`): `Membresia.plan` protege el plan en
   * cuanto tiene una venta, así que el backend nunca borra la fila. */
  eliminar(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }
}
