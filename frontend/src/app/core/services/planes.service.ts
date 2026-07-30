import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, expand, reduce, of } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import { Plan } from '../models/plan.model';

@Injectable({ providedIn: 'root' })
export class PlanesService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/planes`;

  /**
   * `GET /api/planes/` (permiso `membresias.gestionar`). Paginado (DRF
   * `PageNumberPagination`, 20 por página por defecto).
   *
   * DECISIÓN (Parte D del encargo): se piden TODAS las páginas al cargar,
   * siguiendo `next` hasta agotarlo, en vez de añadir un buscador como el
   * de productos. Se eligió esto y no un buscador porque:
   *  - Los planes de membresía de un gimnasio son un catálogo pequeño y
   *    estable (a diferencia del inventario de productos, que puede tener
   *    cientos de referencias): traerlos todos de una vez es barato y
   *    simplifica la UI del selector (no hay que teclear para encontrar un
   *    plan que se usa a diario).
   *  - El POS ya tiene un patrón de "buscar" para productos; duplicarlo
   *    para planes añadiría una interacción extra (escribir para ver algo
   *    que cabe en una lista corta) sin necesidad real.
   *  - Si en el futuro un gimnasio llega a tener decenas de planes activos,
   *    esto seguiría siendo correcto (solo más peticiones secuenciales al
   *    cargar la pantalla), y se puede revisar entonces.
   */
  listar(): Observable<Plan[]> {
    return this.http.get<RespuestaPaginada<Plan>>(`${this.apiUrl}/`).pipe(
      expand((respuesta) =>
        respuesta.next ? this.http.get<RespuestaPaginada<Plan>>(respuesta.next) : of(),
      ),
      reduce<RespuestaPaginada<Plan>, Plan[]>(
        (acumulado, respuesta) => [...acumulado, ...respuesta.results],
        [],
      ),
    );
  }
}
