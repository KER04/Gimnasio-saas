/**
 * Forma de una respuesta paginada de DRF (`PageNumberPagination`, ver
 * `config/settings/base.py::REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS']`,
 * `PAGE_SIZE=20`). Se aplica por defecto a TODOS los `ListAPIView`
 * (productos, planes, clientes) y a los `list()` de `VentaViewSet` — nunca
 * llega un array plano. Comprobado contra el backend real (ver reporte,
 * prueba manual E2E): el primer intento asumía un array plano y el
 * contrato real es este.
 */
export interface RespuestaPaginada<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
