import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AbonoFormulario,
  AnularVentaFormulario,
  EstadoVenta,
  Venta,
  VentaCreada,
  VentaFormulario,
} from '../models/venta.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Ventas y abonos (RF-09). Ambas operaciones exigen `ventas.registrar`.
 *
 * Toda la lógica de negocio vive en el backend
 * (`apps.ventas.services.registrar_venta` / `registrar_abono`): saldo,
 * transición de estado (`pendiente` → `parcial` → `pagada`), tope del abono
 * al saldo pendiente y prohibición de abonar a una venta anulada. Aquí no se
 * replica ninguna de esas reglas; la interfaz solo se adelanta a las obvias
 * para dar mejor mensaje, y el servidor sigue siendo la autoridad.
 */
@Injectable({ providedIn: 'root' })
export class VentasService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/ventas`;

  /** Registra la venta completa: cabecera, líneas, pago inicial (si lo hay)
   * y, para los planes con vigencia, la membresía. */
  registrar(datos: VentaFormulario): Observable<VentaCreada> {
    return this.http.post<VentaCreada>(`${this.base}/`, datos);
  }

  /** Abona sobre el saldo pendiente de una venta. El backend rechaza (400)
   * el abono que supere el saldo, el monto no positivo y la venta anulada. */
  abonar(ventaId: number, datos: AbonoFormulario): Observable<VentaCreada> {
    return this.http.post<VentaCreada>(`${this.base}/${ventaId}/abonos/`, datos);
  }

  /** Historial de ventas, más reciente primero y paginado. */
  listar(
    filtros: { estado?: EstadoVenta; desde?: string; hasta?: string; page?: number } = {},
  ): Observable<RespuestaPaginada<Venta>> {
    let params = new HttpParams();
    for (const [clave, valor] of Object.entries(filtros)) {
      if (valor !== undefined && valor !== '') {
        params = params.set(clave, String(valor));
      }
    }
    return this.http.get<RespuestaPaginada<Venta>>(`${this.base}/`, { params });
  }

  obtener(id: number): Observable<Venta> {
    return this.http.get<Venta>(`${this.base}/${id}/`);
  }

  /**
   * Anula una venta. Exige el permiso `ventas.anular`, MÁS ALTO que el de
   * registrar: deshacer una venta devuelve el stock al inventario y revierte
   * los pagos, así que no debería poder hacerlo cualquiera.
   *
   * El backend rechaza (400) anular una venta ya anulada.
   */
  anular(id: number, datos: AnularVentaFormulario): Observable<Venta> {
    return this.http.post<Venta>(`${this.base}/${id}/anular/`, datos);
  }
}
