/**
 * Sede tal como la devuelve `GET /api/sedes/` (`SedeSerializer`, Parte C del
 * encargo de membresías). Más completa que el `Sede` mínimo de
 * `auth.model.ts` (ese solo trae `id`/`nombre`, embebido en la sesión).
 */
export interface SedeOrganizacion {
  id: number;
  nombre: string;
  direccion: string;
  telefono: string;
  activa: boolean;
}
