import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../environments/environment';
import { RespuestaPaginada } from '../models/paginacion.model';
import {
  RolGimnasio,
  UsuarioConPassword,
  UsuarioEdicion,
  UsuarioFormulario,
  UsuarioGimnasio,
} from '../models/usuario.model';

/** Personal del gimnasio. Todo exige el permiso `config.usuarios`. */
@Injectable({ providedIn: 'root' })
export class UsuariosService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/usuarios`;

  /** Por defecto solo los activos. Con `incluirInactivos` salen todos, que es
   * el único modo de poder reactivar a alguien. */
  listar(incluirInactivos = false): Observable<UsuarioGimnasio[]> {
    const params = incluirInactivos
      ? new HttpParams().set('incluir_inactivos', '1')
      : undefined;
    return this.http
      .get<RespuestaPaginada<UsuarioGimnasio>>(`${this.base}/`, { params })
      .pipe(map((respuesta) => respuesta.results));
  }

  /** La respuesta trae la contraseña generada: es la única vez que se puede
   * leer. */
  crear(datos: UsuarioFormulario): Observable<UsuarioConPassword> {
    return this.http.post<UsuarioConPassword>(`${this.base}/`, datos);
  }

  actualizar(id: number, datos: UsuarioEdicion): Observable<UsuarioGimnasio> {
    return this.http.patch<UsuarioGimnasio>(`${this.base}/${id}/`, datos);
  }

  /** Quita el acceso sin borrar nada. El backend lo rechaza si te lo haces a
   * ti mismo o si dejaría al gimnasio sin ningún administrador. */
  desactivar(id: number): Observable<UsuarioGimnasio> {
    return this.http.post<UsuarioGimnasio>(`${this.base}/${id}/desactivar/`, {});
  }

  activar(id: number): Observable<UsuarioGimnasio> {
    return this.http.post<UsuarioGimnasio>(`${this.base}/${id}/activar/`, {});
  }

  /** Genera una contraseña nueva y la devuelve una sola vez. Cierra las
   * sesiones que ese usuario tuviera abiertas. */
  restablecerPassword(id: number): Observable<UsuarioConPassword> {
    return this.http.post<UsuarioConPassword>(`${this.base}/${id}/restablecer-password/`, {});
  }

  listarRoles(): Observable<RolGimnasio[]> {
    return this.http
      .get<RespuestaPaginada<RolGimnasio>>(`${environment.apiUrl}/roles/`)
      .pipe(map((respuesta) => respuesta.results));
  }
}
