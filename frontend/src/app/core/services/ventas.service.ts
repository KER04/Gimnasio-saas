import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import { AbonoRequest, Venta, VentaCreateRequest } from '../models/venta.model';

@Injectable({ providedIn: 'root' })
export class VentasService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/ventas`;

  /** `POST /api/ventas/` (permiso `ventas.registrar`). */
  registrar(venta: VentaCreateRequest): Observable<Venta> {
    return this.http.post<Venta>(`${this.apiUrl}/`, venta);
  }

  /** `GET /api/ventas/` — respuesta paginada, ver `RespuestaPaginada`. */
  listar(): Observable<RespuestaPaginada<Venta>> {
    return this.http.get<RespuestaPaginada<Venta>>(`${this.apiUrl}/`);
  }

  obtener(id: number): Observable<Venta> {
    return this.http.get<Venta>(`${this.apiUrl}/${id}/`);
  }

  /** `POST /api/ventas/{id}/anular/` (permiso `ventas.anular`). */
  anular(id: number, motivo: string): Observable<Venta> {
    return this.http.post<Venta>(`${this.apiUrl}/${id}/anular/`, { motivo });
  }

  /** `POST /api/ventas/{id}/abonos/` (permiso `ventas.registrar`). */
  registrarAbono(id: number, abono: AbonoRequest): Observable<Venta> {
    return this.http.post<Venta>(`${this.apiUrl}/${id}/abonos/`, abono);
  }
}
