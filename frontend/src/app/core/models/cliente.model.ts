/** Lectura mínima del buscador de clientes del POS (`ClienteResumenSerializer`). */
export interface ClienteResumen {
  id: number;
  nombre: string;
  cedula: string | null;
  telefono: string | null;
  activo: boolean;
}
