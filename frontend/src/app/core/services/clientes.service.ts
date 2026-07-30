import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import { ClienteResumen } from '../models/cliente.model';

@Injectable({ providedIn: 'root' })
export class ClientesService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/clientes`;

  /** `GET /api/clientes/?buscar=<texto>` (permiso `clientes.ver`): busca por
   * nombre o cédula. Respuesta paginada (ver `RespuestaPaginada`). */
  buscar(texto: string): Observable<ClienteResumen[]> {
    return this.http
      .get<RespuestaPaginada<ClienteResumen>>(`${this.apiUrl}/`, {
        params: { buscar: texto },
      })
      .pipe(map((respuesta) => respuesta.results));
  }
}
