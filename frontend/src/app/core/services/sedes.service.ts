import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { SedeOrganizacion } from '../models/sede.model';

/** Listado de sedes del gimnasio (`GET /api/sedes/`), sin paginar. Se usa,
 * por ahora, para el selector de "sede de origen" del formulario de clientes. */
@Injectable({ providedIn: 'root' })
export class SedesService {
  private readonly http = inject(HttpClient);

  listar(): Observable<SedeOrganizacion[]> {
    return this.http.get<SedeOrganizacion[]>(`${environment.apiUrl}/sedes/`);
  }
}
