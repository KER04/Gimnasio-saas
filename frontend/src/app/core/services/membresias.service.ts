import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AsignarMembresiaFormulario,
  CancelarMembresiaFormulario,
  MembresiaCreada,
  MembresiaPorVencer,
  RenovarMembresiaFormulario,
} from '../models/membresia.model';

/**
 * Membresías (`/api/membresias/`). De momento solo la asignación directa,
 * que es lo que necesita la ficha del cliente: hasta ahora la ÚNICA forma de
 * crear una membresía en la app era elegir plan al dar de alta al cliente, y
 * quien se saltaba ese paso se quedaba sin manera de arreglarlo.
 *
 * El backend expone además renovar y cancelar (`POST /api/membresias/{id}/
 * renovar/` y `.../cancelar/`); no se envuelven aquí hasta que haya pantalla
 * que los use.
 */
@Injectable({ providedIn: 'root' })
export class MembresiasService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/membresias`;

  /** Crea la membresía sin venta asociada. Requiere `membresias.gestionar`.
   * El backend rechaza (400) los planes `por_sesion`, que por diseño no
   * generan membresía. */
  asignar(datos: AsignarMembresiaFormulario): Observable<MembresiaCreada> {
    return this.http.post<MembresiaCreada>(`${this.base}/`, datos);
  }

  /**
   * Renueva una membresía creando otra encadenada a ella (la anterior queda
   * intacta). El backend rechaza (400) renovar una cancelada y renovar a un
   * plan `por_sesion`.
   */
  renovar(id: number, datos: RenovarMembresiaFormulario): Observable<MembresiaCreada> {
    return this.http.post<MembresiaCreada>(`${this.base}/${id}/renovar/`, datos);
  }

  /**
   * Cancela una membresía (revoca el acceso). El motivo es obligatorio y
   * queda registrado en auditoría; el backend rechaza (400) cancelar una que
   * ya lo está.
   */
  cancelar(id: number, datos: CancelarMembresiaFormulario): Observable<MembresiaCreada> {
    return this.http.post<MembresiaCreada>(`${this.base}/${id}/cancelar/`, datos);
  }

  /**
   * Tablero de vencimientos (A5): vencidas, que vencen hoy y por vencer,
   * ordenadas por `fecha_fin`. Exige `reportes.ver`, NO `membresias.gestionar`:
   * es una alerta de recepción, no gestión.
   *
   * Viene SIN paginar a propósito (es un tablero de avisos, no un listado),
   * así que la respuesta es un array plano y no `{count, results}`.
   */
  porVencer(): Observable<MembresiaPorVencer[]> {
    return this.http.get<MembresiaPorVencer[]>(`${this.base}/por-vencer/`);
  }
}
