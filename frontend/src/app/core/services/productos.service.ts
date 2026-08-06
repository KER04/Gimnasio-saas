import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import {
  CategoriaFormulario,
  CategoriaProducto,
  MovimientoFormulario,
  MovimientoInventario,
  Producto,
  ProductoFormulario,
} from '../models/producto.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Inventario: catálogo, categorías y kardex.
 *
 * Leer exige `inventario.ver`; crear, editar y dar de baja, `inventario.gestionar`.
 *
 * Las existencias NO se escriben nunca directamente: se mueven registrando
 * un movimiento (`registrarMovimiento`). Un disparador de PostgreSQL es
 * quien actualiza `stock_sedes` y calcula el saldo, de modo que el libro de
 * movimientos y las existencias no puedan desincronizarse.
 */
@Injectable({ providedIn: 'root' })
export class ProductosService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/productos`;
  private readonly baseCategorias = `${environment.apiUrl}/categorias-producto`;
  private readonly baseMovimientos = `${environment.apiUrl}/movimientos-inventario`;

  /**
   * Catálogo para el punto de venta: solo activos.
   *
   * `sede_id` no es opcional en la práctica: sin él el backend devuelve
   * `stock: null` en todas las filas, y vender sin saber las existencias es
   * justo lo que el POS no debe permitir.
   */
  listar(sedeId: number, buscar?: string): Observable<Producto[]> {
    let params = new HttpParams().set('sede_id', String(sedeId));
    if (buscar) {
      params = params.set('buscar', buscar);
    }
    return this.http
      .get<RespuestaPaginada<Producto>>(`${this.base}/`, { params })
      .pipe(map((respuesta) => respuesta.results));
  }

  /** Igual que `listar()`, pero incluye los dados de baja: la pantalla de
   * inventario los necesita para poder reactivarlos. */
  listarTodos(sedeId: number, buscar?: string): Observable<Producto[]> {
    let params = new HttpParams().set('sede_id', String(sedeId)).set('incluir_inactivos', '1');
    if (buscar) {
      params = params.set('buscar', buscar);
    }
    return this.http
      .get<RespuestaPaginada<Producto>>(`${this.base}/`, { params })
      .pipe(map((respuesta) => respuesta.results));
  }

  crear(datos: ProductoFormulario): Observable<Producto> {
    return this.http.post<Producto>(`${this.base}/`, datos);
  }

  actualizar(id: number, datos: Partial<ProductoFormulario>): Observable<Producto> {
    return this.http.patch<Producto>(`${this.base}/${id}/`, datos);
  }

  /** Borrado LÓGICO (`activo=false`): `DetalleVenta.producto` protege el
   * producto en cuanto se ha vendido una vez. */
  eliminar(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }

  // --- Categorías ---

  listarCategorias(incluirInactivas = false): Observable<CategoriaProducto[]> {
    const params = incluirInactivas ? new HttpParams().set('incluir_inactivos', '1') : undefined;
    return this.http
      .get<RespuestaPaginada<CategoriaProducto>>(`${this.baseCategorias}/`, { params })
      .pipe(map((respuesta) => respuesta.results));
  }

  crearCategoria(datos: CategoriaFormulario): Observable<CategoriaProducto> {
    return this.http.post<CategoriaProducto>(`${this.baseCategorias}/`, datos);
  }

  actualizarCategoria(id: number, datos: Partial<CategoriaFormulario>): Observable<CategoriaProducto> {
    return this.http.patch<CategoriaProducto>(`${this.baseCategorias}/${id}/`, datos);
  }

  /** También lógico: `Producto.categoria_producto` es `PROTECT`. */
  eliminarCategoria(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseCategorias}/${id}/`);
  }

  // --- Kardex ---

  /** Registra una entrada o un ajuste. El backend rechaza (400) el ajuste
   * sin motivo, la entrada con cantidad negativa y el movimiento que dejaría
   * el stock por debajo de cero. */
  registrarMovimiento(datos: MovimientoFormulario): Observable<MovimientoInventario> {
    return this.http.post<MovimientoInventario>(`${this.baseMovimientos}/`, datos);
  }

  listarMovimientos(filtros: { producto?: number; sede?: number } = {}): Observable<MovimientoInventario[]> {
    let params = new HttpParams();
    for (const [clave, valor] of Object.entries(filtros)) {
      if (valor !== undefined) {
        params = params.set(clave, String(valor));
      }
    }
    return this.http
      .get<RespuestaPaginada<MovimientoInventario>>(`${this.baseMovimientos}/`, { params })
      .pipe(map((respuesta) => respuesta.results));
  }
}
