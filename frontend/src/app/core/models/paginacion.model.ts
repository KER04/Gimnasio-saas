/**
 * Forma estándar de cualquier listado paginado del backend
 * (`rest_framework.pagination.PageNumberPagination`, `PAGE_SIZE=20`).
 */
export interface RespuestaPaginada<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
