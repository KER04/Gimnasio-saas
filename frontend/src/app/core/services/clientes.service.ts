import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AsistenciaCliente,
  Cliente,
  ClienteFormulario,
  ClienteResumen,
  CompraCliente,
  DeudaCliente,
  MembresiaResumen,
} from '../models/cliente.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Los nueve endpoints de `/api/clientes/` (RF-03/RF-09/RF-16): listar+buscar,
 * crear, ver detalle, editar, borrado lógico, y las cuatro consultas de
 * ficha (membresías, deuda, compras, asistencias).
 */
@Injectable({ providedIn: 'root' })
export class ClientesService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/clientes`;

  /** Busca por nombre o cédula en el mismo campo (`buscar`), paginado. */
  listar(buscar?: string, page?: number): Observable<RespuestaPaginada<ClienteResumen>> {
    let params = new HttpParams();
    if (buscar) {
      params = params.set('buscar', buscar);
    }
    if (page) {
      params = params.set('page', page);
    }
    return this.http.get<RespuestaPaginada<ClienteResumen>>(`${this.base}/`, { params });
  }

  crear(datos: ClienteFormulario): Observable<Cliente> {
    return this.http.post<Cliente>(`${this.base}/`, datos);
  }

  obtener(id: number): Observable<Cliente> {
    return this.http.get<Cliente>(`${this.base}/${id}/`);
  }

  actualizar(id: number, datos: Partial<ClienteFormulario>): Observable<Cliente> {
    return this.http.patch<Cliente>(`${this.base}/${id}/`, datos);
  }

  /** Borrado LÓGICO: el cliente desaparece del listado pero su histórico de
   * ventas se conserva (la fila sigue existiendo con `eliminado_en` fijado). */
  eliminar(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }

  /** Todas las membresías del cliente con su estado YA calculado (RF-16):
   * puede haber varias activas a la vez. */
  membresias(id: number): Observable<MembresiaResumen[]> {
    return this.http.get<MembresiaResumen[]>(`${this.base}/${id}/membresias/`);
  }

  /** Cartera del cliente (RF-09): total adeudado y, por venta, sus abonos
   * en orden cronológico. */
  deuda(id: number): Observable<DeudaCliente> {
    return this.http.get<DeudaCliente>(`${this.base}/${id}/deuda/`);
  }

  /** Historial de compras, más reciente primero, paginado. Incluye las
   * ventas anuladas (marcadas, no ocultas). */
  compras(id: number, page?: number): Observable<RespuestaPaginada<CompraCliente>> {
    let params = new HttpParams();
    if (page) {
      params = params.set('page', page);
    }
    return this.http.get<RespuestaPaginada<CompraCliente>>(`${this.base}/${id}/compras/`, { params });
  }

  /** Historial de asistencia, más reciente primero, paginado. */
  asistencias(id: number, page?: number): Observable<RespuestaPaginada<AsistenciaCliente>> {
    let params = new HttpParams();
    if (page) {
      params = params.set('page', page);
    }
    return this.http.get<RespuestaPaginada<AsistenciaCliente>>(`${this.base}/${id}/asistencias/`, { params });
  }
}
