import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import { Producto } from '../models/producto.model';

@Injectable({ providedIn: 'root' })
export class ProductosService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/productos`;

  /** `GET /api/productos/?buscar=<texto>&sede_id=<id>` (permiso `inventario.ver`).
   * Respuesta paginada (DRF `PageNumberPagination`, ver `RespuestaPaginada`). */
  buscar(texto: string, sedeId: number): Observable<Producto[]> {
    return this.http
      .get<RespuestaPaginada<Producto>>(`${this.apiUrl}/`, {
        params: { buscar: texto, sede_id: sedeId },
      })
      .pipe(map((respuesta) => respuesta.results));
  }
}
