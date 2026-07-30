export interface Plan {
  id: number;
  nombre: string;
  tipo: 'mensual' | 'quincenal' | 'por_sesion';
  duracion_dias: number;
  precio: string;
  requiere_entrenador: boolean;
  sede: number | null;
  activo: boolean;
}
