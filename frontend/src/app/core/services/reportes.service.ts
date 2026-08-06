import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  ReporteCaja,
  ReporteCartera,
  ReporteProductos,
  ReporteUtilidad,
  ReporteVentas,
} from '../models/reporte.model';

/** Filtros comunes a los tres informes. Las fechas van en `YYYY-MM-DD`. */
export interface FiltroReporte {
  desde?: string;
  hasta?: string;
  sede?: number;
}

/**
 * Informes (RF-08). Los tres exigen `reportes.ver` y son de solo lectura:
 * agregan datos que ya existen, no guardan nada.
 */
@Injectable({ providedIn: 'root' })
export class ReportesService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/reportes`;

  private params(filtros: FiltroReporte, extra: Record<string, string> = {}): HttpParams {
    let params = new HttpParams();
    for (const [clave, valor] of Object.entries({ ...filtros, ...extra })) {
      if (valor !== undefined && valor !== '') {
        params = params.set(clave, String(valor));
      }
    }
    return params;
  }

  /** Facturado, cobrado y por cobrar, con el desglose por estado. */
  ventas(filtros: FiltroReporte = {}): Observable<ReporteVentas> {
    return this.http.get<ReporteVentas>(`${this.base}/ventas/`, { params: this.params(filtros) });
  }

  /** Dinero recibido por día o por mes, con el desglose por forma de pago.
   * Se apoya en `v_corte_diario`, que ya agrupa en la zona horaria del
   * gimnasio y excluye ventas y pagos anulados. */
  caja(filtros: FiltroReporte = {}, agrupar: 'dia' | 'mes' = 'dia'): Observable<ReporteCaja> {
    return this.http.get<ReporteCaja>(`${this.base}/caja/`, {
      params: this.params(filtros, { agrupar }),
    });
  }

  /**
   * Quién debe y cuánto, por cliente y con el detalle de cada venta.
   *
   * Sin rango de fechas a propósito: una deuda sigue viva hasta que se
   * cobra, así que acotarla por periodo daría menos de lo que se debe de
   * verdad, que es justo lo contrario de lo que hace falta para ir a cobrar.
   */
  cartera(sede?: number): Observable<ReporteCartera> {
    return this.http.get<ReporteCartera>(`${this.base}/cartera/`, {
      params: this.params(sede === undefined ? {} : { sede }),
    });
  }

  /**
   * Márgenes: qué se ganó con lo vendido, producto a producto.
   *
   * Exige `costos.ver` y NO `reportes.ver`: es el permiso que separa a quien
   * puede ver costos de quien no, y este informe es justo esos costos
   * agregados. Sin él, el backend responde 403.
   */
  utilidad(filtros: FiltroReporte = {}): Observable<ReporteUtilidad> {
    return this.http.get<ReporteUtilidad>(`${this.base}/utilidad/`, { params: this.params(filtros) });
  }

  /** Unidades e importe vendidos por producto, más sus existencias actuales. */
  productos(filtros: FiltroReporte = {}): Observable<ReporteProductos> {
    return this.http.get<ReporteProductos>(`${this.base}/productos/`, { params: this.params(filtros) });
  }
}
