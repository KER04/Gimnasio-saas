import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { SedeOrganizacion } from '../models/sede.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/** Listado de sedes del gimnasio (`GET /api/sedes/`). Se usa, por ahora, para
 * el selector de "sede de origen" del formulario de clientes.
 *
 * CORRECCIÓN: el endpoint SÍ viene paginado (`PageNumberPagination` global
 * del proyecto, `PAGE_SIZE=20`, ver `config/settings/base.py`) aunque la
 * vista (`SedeListView`) no lo declare explícitamente — comprobado contra el
 * backend real, que devuelve `{count, next, previous, results}` y no un
 * array plano. La firma anterior (`Observable<SedeOrganizacion[]>` leyendo
 * el cuerpo tal cual) nunca coincidió con la forma real de la respuesta. */
@Injectable({ providedIn: 'root' })
export class SedesService {
  private readonly http = inject(HttpClient);

  listar(): Observable<SedeOrganizacion[]> {
    return this.http
      .get<RespuestaPaginada<SedeOrganizacion>>(`${environment.apiUrl}/sedes/`)
      .pipe(map((respuesta) => respuesta.results));
  }
}
