import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Asistencia,
  RegistrarAsistenciaFormulario,
  VerificacionAsistencia,
} from '../models/asistencia.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Asistencia (RF-15). Los tres endpoints exigen permisos DISTINTOS, y no por
 * capricho: consultar es rutinario, registrar mueve el aforo y el historial
 * es un informe.
 *
 * - `verificar` → `clientes.ver`
 * - `registrar` → `ventas.registrar`
 * - `listar`    → `reportes.ver`
 */
@Injectable({ providedIn: 'root' })
export class AsistenciasService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/asistencias`;

  /**
   * Panel del recepcionista: dice si el cliente puede pasar y por qué, SIN
   * registrar nada. Devuelve 404 si la cédula no existe en el gimnasio.
   */
  verificar(cedula: string): Observable<VerificacionAsistencia> {
    return this.http.get<VerificacionAsistencia>(`${this.base}/verificar/`, {
      params: new HttpParams().set('cedula', cedula),
    });
  }

  /**
   * Registra el ingreso. El backend distingue tres respuestas de error que
   * NO significan lo mismo:
   * - **409** antipassback: ya entró hace poco. No es un fallo, es la regla.
   * - **403** quien autoriza no tiene `asistencia.autorizar`.
   * - **400** el resto (cédula inexistente, falta el motivo, etc.).
   */
  registrar(datos: RegistrarAsistenciaFormulario): Observable<Asistencia> {
    return this.http.post<Asistencia>(`${this.base}/`, datos);
  }

  /** Historial, más reciente primero y paginado. Filtros opcionales por
   * cliente, sede y rango de fechas (`YYYY-MM-DD`). */
  listar(filtros: { cliente?: number; sede?: number; desde?: string; hasta?: string; page?: number } = {}):
    Observable<RespuestaPaginada<Asistencia>> {
    let params = new HttpParams();
    for (const [clave, valor] of Object.entries(filtros)) {
      if (valor !== undefined && valor !== '') {
        params = params.set(clave, String(valor));
      }
    }
    return this.http.get<RespuestaPaginada<Asistencia>>(`${this.base}/`, { params });
  }
}
