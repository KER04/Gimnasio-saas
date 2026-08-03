import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { Plan } from '../models/plan.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Catálogo de planes (`GET /api/planes/`), usado por el selector de "Plan"
 * del listado de clientes y por la selección de plan del alta (RF-03).
 *
 * El endpoint viene paginado (`PageNumberPagination` global, `PAGE_SIZE=20`),
 * pero para estos dos usos hace falta el catálogo completo de una vez (un
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
}
