import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';

/** Una sede tal como la ve la pantalla de gestión: más campos que el
 * selector de `GET /api/sedes/`, que solo necesita id y nombre. */
export interface SedeAdmin {
  id: number;
  nombre: string;
  direccion: string;
  telefono: string | null;
  nit: string | null;
  encabezado_recibo: string | null;
  /** Prefijo del número de recibo. Cambiarlo NO renumera lo ya emitido. */
  prefijo_comprobante: string;
  activa: boolean;
}

export interface SedeFormulario {
  nombre: string;
  direccion: string;
  telefono?: string | null;
  nit?: string | null;
  encabezado_recibo?: string | null;
  prefijo_comprobante?: string;
}

/** Respuesta al cerrar una sede: avisa de quién se queda sin ninguna. */
export interface SedeCerrada extends SedeAdmin {
  usuarios_sin_sede: string[];
}

/**
 * Gestión de sedes (`config.sedes`).
 *
 * Aparte de `SedesService`, que es el selector que usa toda la aplicación
 * para saber dónde trabajas: ese solo pide estar autenticado.
 */
@Injectable({ providedIn: 'root' })
export class SedesAdminService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/sedes-admin`;

  /** Devuelve TODAS, activas y cerradas: es la única forma de reabrir una. */
  listar(): Observable<SedeAdmin[]> {
    return this.http.get<SedeAdmin[]>(`${this.base}/`);
  }

  crear(datos: SedeFormulario): Observable<SedeAdmin> {
    return this.http.post<SedeAdmin>(`${this.base}/`, datos);
  }

  actualizar(id: number, datos: Partial<SedeFormulario>): Observable<SedeAdmin> {
    return this.http.patch<SedeAdmin>(`${this.base}/${id}/`, datos);
  }

  /** Cierra la sede. El backend lo rechaza si es la única activa. */
  desactivar(id: number): Observable<SedeCerrada> {
    return this.http.post<SedeCerrada>(`${this.base}/${id}/desactivar/`, {});
  }

  activar(id: number): Observable<SedeAdmin> {
    return this.http.post<SedeAdmin>(`${this.base}/${id}/activar/`, {});
  }
}
